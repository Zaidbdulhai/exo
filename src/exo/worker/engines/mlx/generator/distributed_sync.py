"""Distributed sync utilities using mx.distributed.all_sum() to broadcast from rank 0."""

# pyright: reportAny=false

import pickle
from typing import TypeVar, cast

import mlx.core as mx

from exo.worker.runner.bootstrap import logger

T = TypeVar("T")


def share_object(obj: T | None, rank: int, group: mx.distributed.Group) -> T | None:
    """Broadcast object from rank 0 to all ranks. Two-phase: size then data."""
    logger.debug(f"share_object: rank={rank}, obj_type={type(obj).__name__ if obj else 'None'}")
    if rank == 0:
        if obj is None:
            logger.debug("share_object: rank 0 broadcasting None (size=0)")
            mx.eval(mx.distributed.all_sum(mx.array([0]), group=group))
            logger.debug("share_object: rank 0 broadcast None complete")
            return None
        data = mx.array(list(pickle.dumps(obj)), dtype=mx.uint8)
        logger.debug(f"share_object: rank 0 broadcasting size={data.size}")
        mx.eval(mx.distributed.all_sum(mx.array([data.size]), group=group))
        logger.debug("share_object: rank 0 broadcasting data")
        mx.eval(mx.distributed.all_sum(data, group=group))
        logger.debug("share_object: rank 0 broadcast complete")
        return obj
    else:
        logger.debug("share_object: non-rank-0 waiting for size")
        size = int(mx.distributed.all_sum(mx.array([0]), group=group).item())
        logger.debug(f"share_object: non-rank-0 received size={size}")
        if size == 0:
            return None
        data = mx.zeros(size, dtype=mx.uint8)
        logger.debug("share_object: non-rank-0 waiting for data")
        data = mx.distributed.all_sum(data, group=group)
        mx.eval(data)
        logger.debug("share_object: non-rank-0 received data")
        return cast(T, pickle.loads(bytes(cast(list[int], data.tolist()))))
