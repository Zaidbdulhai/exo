import gc
import time

import mlx.core as mx
from anyio import WouldBlock

from exo.shared.types.api import ChatCompletionMessageText
from exo.shared.types.chunks import TokenChunk
from exo.shared.types.events import (
    ChunkGenerated,
    Event,
    RunnerStatusUpdated,
    TaskAcknowledged,
    TaskStatusUpdated,
)
from exo.shared.types.common import CommandId
from exo.shared.types.tasks import (
    ChatCompletion,
    ConnectToGroup,
    LoadModel,
    Shutdown,
    StartWarmup,
    Task,
    TaskId,
    TaskStatus,
)
from exo.shared.types.worker.instances import BoundInstance
from exo.shared.types.worker.runner_response import GenerationResponse
from exo.shared.types.worker.runners import (
    RunnerConnected,
    RunnerConnecting,
    RunnerFailed,
    RunnerIdle,
    RunnerLoaded,
    RunnerLoading,
    RunnerReady,
    RunnerRunning,
    RunnerShutdown,
    RunnerShuttingDown,
    RunnerStatus,
    RunnerWarmingUp,
)
from exo.utils.channels import MpReceiver, MpSender
from exo.worker.engines.mlx.generator.batch_engine import BatchGenerationEngine
from exo.worker.engines.mlx.generator.distributed_sync import share_object
from exo.worker.engines.mlx.generator.generate import warmup_inference
from exo.worker.engines.mlx.generator.time_budget import TimeBudget
from exo.worker.engines.mlx.utils_mlx import (
    initialize_mlx,
    load_mlx_items,
    mlx_force_oom,
)
from exo.worker.runner.bootstrap import logger


def main(
    bound_instance: BoundInstance,
    event_sender: MpSender[Event],
    task_receiver: MpReceiver[Task],
):
    instance, runner_id, shard_metadata = (
        bound_instance.instance,
        bound_instance.bound_runner_id,
        bound_instance.bound_shard,
    )
    logger.info("hello from the runner")
    if getattr(shard_metadata, "immediate_exception", False):
        raise Exception("Fake exception - runner failed to spin up.")
    if timeout := getattr(shard_metadata, "should_timeout", 0):
        time.sleep(timeout)

    setup_start_time = time.time()

    model = None
    tokenizer = None
    group = None
    batch_engine: BatchGenerationEngine | None = None
    pending_shutdown: Shutdown | None = None

    current_status: RunnerStatus = RunnerIdle()

    def send_status(status: RunnerStatus) -> None:
        event_sender.send(RunnerStatusUpdated(runner_id=runner_id, runner_status=status))

    logger.info("runner created")
    send_status(current_status)

    def handle_task(task: Task, is_deferred: bool = False) -> bool:
        nonlocal current_status, model, tokenizer, group, batch_engine, pending_shutdown

        # For Shutdown, check if we need to defer BEFORE sending Running/Acknowledged
        if isinstance(task, Shutdown) and not is_deferred:
            if batch_engine is not None and (batch_engine.has_active_requests or batch_engine.has_pending_inserts):
                logger.info("deferring shutdown until active requests complete")
                pending_shutdown = task
                return True

        event_sender.send(TaskStatusUpdated(task_id=task.task_id, task_status=TaskStatus.Running))
        event_sender.send(TaskAcknowledged(task_id=task.task_id))

        match task:
            case ConnectToGroup() if isinstance(
                current_status, (RunnerIdle, RunnerFailed)
            ):
                logger.info("runner connecting")
                current_status = RunnerConnecting()
                send_status(current_status)
                group = initialize_mlx(bound_instance)

                logger.info("runner connected")
                current_status = RunnerConnected()
                event_sender.send(TaskStatusUpdated(task_id=task.task_id, task_status=TaskStatus.Complete))
                send_status(current_status)

            case LoadModel() if (
                isinstance(current_status, RunnerConnected) and group is not None
            ) or (isinstance(current_status, RunnerIdle) and group is None):
                current_status = RunnerLoading()
                logger.info("runner loading")
                send_status(current_status)

                model, tokenizer = load_mlx_items(bound_instance, group)

                current_status = RunnerLoaded()
                logger.info("runner loaded")
                event_sender.send(TaskStatusUpdated(task_id=task.task_id, task_status=TaskStatus.Complete))
                send_status(current_status)

            case StartWarmup() if isinstance(current_status, RunnerLoaded):
                assert model is not None
                assert tokenizer is not None
                current_status = RunnerWarmingUp()
                logger.info("runner warming up")
                send_status(current_status)

                logger.info(f"warming up inference for instance: {instance}")
                toks = warmup_inference(model=model, tokenizer=tokenizer)
                logger.info(f"warmed up by generating {toks} tokens")
                logger.info(f"runner initialized in {time.time() - setup_start_time} seconds")

                batch_engine = BatchGenerationEngine(model=model, tokenizer=tokenizer, group=group)

                current_status = RunnerReady()
                logger.info("runner ready")
                event_sender.send(TaskStatusUpdated(task_id=task.task_id, task_status=TaskStatus.Complete))
                send_status(current_status)

            case ChatCompletion(
                task_params=task_params, command_id=command_id
            ) if isinstance(current_status, (RunnerReady, RunnerRunning)):
                assert batch_engine is not None

                # In distributed mode, only rank 0 should queue requests
                # Other ranks should skip - they'll participate in sync_and_insert_pending()
                is_distributed_mode = group is not None and isinstance(group.size(), int) and group.size() > 1
                if is_distributed_mode and shard_metadata.device_rank != 0:
                    logger.debug(f"Rank {shard_metadata.device_rank} skipping ChatCompletionTask (only rank 0 queues)")
                    return True

                if task_params.messages and task_params.messages[0].content is not None:
                    _check_for_debug_prompts(task_params.messages[0].content)

                # Queue the request - actual insertion happens in sync_and_insert_pending()
                batch_engine.queue_request(command_id=command_id, task_id=task.task_id, task_params=task_params)

                # Status will be updated after actual insertion in the main loop
                # For now, set to RunnerRunning to indicate we're processing
                current_status = RunnerRunning(active_requests=batch_engine.active_count + batch_engine.pending_insert_count)
                send_status(current_status)

            case Shutdown():
                current_status = RunnerShuttingDown()
                logger.info("runner shutting down")
                send_status(current_status)
                event_sender.send(TaskStatusUpdated(task_id=task.task_id, task_status=TaskStatus.Complete))
                current_status = RunnerShutdown()
                send_status(current_status)
                return False

            case _:
                raise ValueError(
                    f"Received {task.__class__.__name__} outside of state machine in {current_status=}"
                )

        return True

    with task_receiver as tasks:
        running = True
        is_rank_0 = shard_metadata.device_rank == 0
        is_distributed = group is not None and group.size() > 1

        # Accumulated responses to send at budget boundary
        pending_responses: list[tuple[CommandId, TaskId, GenerationResponse]] = []

        while running:
            if is_distributed:
                assert group is not None
                assert batch_engine is not None

                # Distributed mode: sync at time budget boundaries, not per-token
                # Step 1: Only rank 0 checks for new tasks
                should_shutdown = False
                if is_rank_0:
                    while True:
                        try:
                            task = tasks.receive_nowait()
                            task_result = handle_task(task)
                            if not task_result:
                                should_shutdown = True
                                break
                        except WouldBlock:
                            break

                    # Check for deferred shutdown when no more active requests
                    if pending_shutdown is not None and not batch_engine.has_active_requests and not batch_engine.has_pending_inserts:
                        should_shutdown = True

                # Step 2: Sync shutdown flag across all ranks
                synced_shutdown = share_object(should_shutdown if is_rank_0 else None, shard_metadata.device_rank, group)
                if synced_shutdown:
                    running = False
                    if is_rank_0 and pending_shutdown is not None:
                        handle_task(pending_shutdown, is_deferred=True)
                    continue

                # Step 3: Sync and insert any pending requests
                # All ranks must participate in sync_and_insert_pending (collective op)
                # If rank 0 has no pending, it broadcasts empty list and all return early
                inserted = batch_engine.sync_and_insert_pending()
                if is_rank_0 and inserted:
                    current_status = RunnerRunning(active_requests=batch_engine.active_count)
                    send_status(current_status)

                # Step 4: Run generation for time budget (no per-token sync)
                if batch_engine.has_active_requests:
                    time_budget = TimeBudget(budget=0.5, group=group)
                    for _ in time_budget:
                        if not batch_engine.has_active_requests:
                            break
                        for resp in batch_engine.step():
                            # Accumulate responses to send at budget boundary
                            pending_responses.append((resp.command_id, resp.task_id, resp.response))

                # Step 5: Sync completions at budget boundary
                batch_engine.sync_completions()

                # Step 6: Send accumulated responses (only rank 0)
                if is_rank_0:
                    for command_id, task_id, response in pending_responses:
                        event_sender.send(ChunkGenerated(
                            command_id=command_id,
                            chunk=TokenChunk(
                                idx=response.token,
                                model=shard_metadata.model_meta.model_id,
                                text=response.text,
                                token_id=response.token,
                                finish_reason=response.finish_reason,
                                stats=response.stats,
                            ),
                        ))
                        if response.finish_reason is not None:
                            event_sender.send(TaskStatusUpdated(task_id=task_id, task_status=TaskStatus.Complete))

                    if batch_engine.has_active_requests:
                        current_status = RunnerRunning(active_requests=batch_engine.active_count)
                    else:
                        current_status = RunnerReady()
                    send_status(current_status)

                pending_responses.clear()

                # Short sleep if nothing to do (will check for new tasks on next iteration)
                if not batch_engine.has_active_requests and not batch_engine.has_pending_inserts:
                    time.sleep(0.001)

            else:
                # Non-distributed mode: original logic with queue + insert
                while True:
                    try:
                        task = tasks.receive_nowait()
                        running = handle_task(task)
                        if not running:
                            break
                    except WouldBlock:
                        break

                if not running:
                    break

                # Insert any queued requests (non-distributed just inserts directly)
                # Status was already sent in handle_task when queueing
                if batch_engine is not None and batch_engine.has_pending_inserts:
                    batch_engine.sync_and_insert_pending()

                if batch_engine is not None and batch_engine.has_active_requests:
                    for resp in batch_engine.step():
                        if shard_metadata.device_rank == 0:
                            event_sender.send(ChunkGenerated(
                                command_id=resp.command_id,
                                chunk=TokenChunk(
                                    idx=resp.response.token,
                                    model=shard_metadata.model_meta.model_id,
                                    text=resp.response.text,
                                    token_id=resp.response.token,
                                    finish_reason=resp.response.finish_reason,
                                    stats=resp.response.stats,
                                ),
                            ))
                        if resp.response.finish_reason is not None:
                            event_sender.send(TaskStatusUpdated(task_id=resp.task_id, task_status=TaskStatus.Complete))

                    if batch_engine.has_active_requests:
                        current_status = RunnerRunning(active_requests=batch_engine.active_count)
                    else:
                        current_status = RunnerReady()
                    send_status(current_status)

                    # Process deferred shutdown after all requests complete
                    if pending_shutdown is not None and not batch_engine.has_active_requests and not batch_engine.has_pending_inserts:
                        running = handle_task(pending_shutdown, is_deferred=True)
                else:
                    task = tasks.receive()
                    running = handle_task(task)

    # Cleanup
    del model, tokenizer, group, batch_engine
    mx.clear_cache()
    gc.collect()


EXO_RUNNER_MUST_FAIL = "EXO RUNNER MUST FAIL"
EXO_RUNNER_MUST_OOM = "EXO RUNNER MUST OOM"
EXO_RUNNER_MUST_TIMEOUT = "EXO RUNNER MUST TIMEOUT"


def _check_for_debug_prompts(
    prompt: str | ChatCompletionMessageText | list[ChatCompletionMessageText],
):
    if isinstance(prompt, list):
        if len(prompt) == 0:
            logger.debug("Empty message prompt received in debug prompt")
            return
        prompt = prompt[0]

    if isinstance(prompt, ChatCompletionMessageText):
        prompt = prompt.text

    if EXO_RUNNER_MUST_FAIL in prompt:
        logger.info("raising exception")
        raise Exception("Artificial runner exception - for testing purposes only.")
    if EXO_RUNNER_MUST_OOM in prompt:
        mlx_force_oom()
    if EXO_RUNNER_MUST_TIMEOUT in prompt:
        time.sleep(100)
