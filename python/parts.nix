{ inputs, ... }:
{
  perSystem =
    { config, self', pkgs, lib, system, ... }:
    let
      # Load workspace from uv.lock
      workspace = inputs.uv2nix.lib.workspace.loadWorkspace {
        workspaceRoot = inputs.self;
      };

      # Create overlay from workspace
      # Use wheels for now - building from source requires more complex
      # build system resolution that we can investigate later
      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      # Override overlay to inject Nix-built components
      exoOverlay = final: prev: {
        # Replace editable exo_pyo3_bindings with Nix-built wheel
        exo-pyo3-bindings = pkgs.stdenv.mkDerivation {
          pname = "exo-pyo3-bindings";
          version = "0.1.0";
          src = self'.packages.exo_pyo3_bindings;
          # Install from pre-built wheel
          nativeBuildInputs = [ final.pyprojectWheelHook ];
          dontStrip = true;
        };
      };

      python = pkgs.python313;

      # Overlay to provide build systems for source builds and platform stubs
      buildSystemsOverlay = final: prev:
        # On Darwin, mlx-lm is a git dependency that needs setuptools
        lib.optionalAttrs pkgs.stdenv.hostPlatform.isDarwin
          {
            mlx-lm = prev.mlx-lm.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
                final.setuptools
              ];
            });
          }
        # On Linux, MLX packages don't work (require Metal framework)
        # Provide minimal stubs so the build can complete
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          mlx = pkgs.stdenv.mkDerivation {
            pname = "mlx";
            version = "0.30.1";
            dontUnpack = true;
            installPhase = ''
              mkdir -p $out/${python.sitePackages}/mlx
              echo 'raise ImportError("MLX requires macOS with Apple Silicon")' > $out/${python.sitePackages}/mlx/__init__.py
            '';
          };
          mlx-cpu = pkgs.stdenv.mkDerivation {
            pname = "mlx-cpu";
            version = "0.30.1";
            dontUnpack = true;
            installPhase = ''
              mkdir -p $out/${python.sitePackages}
              touch $out/${python.sitePackages}/mlx_cpu_stub.py
            '';
          };
          mlx-lm = pkgs.stdenv.mkDerivation {
            pname = "mlx-lm";
            version = "0.30.2";
            dontUnpack = true;
            installPhase = ''
              mkdir -p $out/${python.sitePackages}/mlx_lm
              echo 'raise ImportError("mlx-lm requires macOS with Apple Silicon")' > $out/${python.sitePackages}/mlx_lm/__init__.py
            '';
          };
        };

      pythonSet = (pkgs.callPackage inputs.pyproject-nix.build.packages {
        inherit python;
      }).overrideScope (
        lib.composeManyExtensions [
          inputs.pyproject-build-systems.overlays.default
          overlay
          exoOverlay
          buildSystemsOverlay
        ]
      );
      exoVenv = pythonSet.mkVirtualEnv "exo-env" workspace.deps.default;

      exoPackage = pkgs.runCommand "exo"
        {
          nativeBuildInputs = [ pkgs.makeWrapper ];
        }
        ''
          mkdir -p $out/bin $out/share/exo

          # Copy dashboard
          cp -r ${self'.packages.dashboard} $out/share/exo/dashboard

          # Copy system_custodian binary
          cp ${self'.packages.system_custodian}/bin/system_custodian $out/bin/

          # Create wrapper scripts
          for script in exo exo-master exo-worker; do
            makeWrapper ${exoVenv}/bin/$script $out/bin/$script \
              --set DASHBOARD_DIR $out/share/exo/dashboard
          done
        '';

      pyinstallerPackage =
        let
          venv = pythonSet.mkVirtualEnv "exo-pyinstaller-env" (
            workspace.deps.default
            // {
              # Include pyinstaller in the environment
              exo = [ "dev" ];
            }
          );
        in
        pkgs.stdenv.mkDerivation {
          pname = "exo-pyinstaller";
          version = "0.3.0";

          src = inputs.self;

          nativeBuildInputs = [ venv pkgs.makeWrapper pkgs.macmon pkgs.darwin.system_cmds ];

          buildPhase = ''
            # macmon must be in PATH for PyInstaller to bundle it
            export PATH="${pkgs.macmon}/bin:$PATH"
            # HOME must be writable for PyInstaller's cache
            export HOME="$TMPDIR"

            # Copy dashboard to expected location
            mkdir -p dashboard/build
            cp -r ${self'.packages.dashboard}/* dashboard/build/

            # Run PyInstaller
            ${venv}/bin/python -m PyInstaller packaging/pyinstaller/exo.spec
          '';

          installPhase = ''
            cp -r dist/exo $out
          '';
        };
    in
    {
      packages = {
        exo = exoPackage;
      } // lib.optionalAttrs pkgs.stdenv.hostPlatform.isDarwin {
        exo-pyinstaller = pyinstallerPackage;
      };

      # Python checks
      checks = {
        # Ruff linting
        lint = pkgs.runCommand "ruff-lint" { } ''
          export RUFF_CACHE_DIR="$TMPDIR/ruff-cache"
          ${pkgs.ruff}/bin/ruff check ${inputs.self}/
          touch $out
        '';
      };
    };
}
