{
  description = "Nohiki development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        python = pkgs.python314;
        nodejs = pkgs.nodejs_26;
        corepackPackage = pkgs.corepack.override { nodejs-slim = nodejs; };
        uvRelease = {
          x86_64-linux = {
            target = "x86_64-unknown-linux-gnu";
            sha256 = "e490a6464492183c5d4534a5527fb4440f7f2bb2f228162ad7e4afe076dc0224";
          };
          aarch64-linux = {
            target = "aarch64-unknown-linux-gnu";
            sha256 = "03e9fe0a81b0718d0bc84625de3885df6cc3f89a8b6af6121d6b9f6113fb6533";
          };
          x86_64-darwin = {
            target = "x86_64-apple-darwin";
            sha256 = "2ad79983127ffca7d77b77ce6a24278d7e4f7b817a1acf72fea5f8124b4aac5e";
          };
          aarch64-darwin = {
            target = "aarch64-apple-darwin";
            sha256 = "33540eb7c883ab857eff79bd5ac2aa31fe27b595abecb4a9c003a2c998447232";
          };
        }.${system};
        uvPackage = pkgs.stdenvNoCC.mkDerivation {
          pname = "uv";
          version = "0.11.28";
          src = pkgs.fetchurl {
            url = "https://github.com/astral-sh/uv/releases/download/0.11.28/uv-${uvRelease.target}.tar.gz";
            inherit (uvRelease) sha256;
          };
          sourceRoot = "uv-${uvRelease.target}";
          installPhase = ''
            mkdir -p "$out/bin"
            install -m755 uv uvx "$out/bin/"
          '';
        };

        lefthookVersion = "2.1.10";
        lefthookPackage = pkgs.buildGo126Module {
          pname = "lefthook";
          version = lefthookVersion;

          src = pkgs.fetchFromGitHub {
            owner = "evilmartians";
            repo = "lefthook";
            rev = "8d9cfec5f52367af6374a5430b4e9568844856e5";
            hash = "sha256-GR97Z9wnM6z6gNIcf35leBGkhdj1d6OHQ9oFnaz3f1s=";
          };

          vendorHash = "sha256-G+v6ZqnkcFdPDzXlN89oqD7mOnHfq1tvIkFxdoVnBNo=";

          ldflags = [ "-s" "-w" ];
          doCheck = false;

          meta = {
            description = "Fast and powerful Git hooks manager";
            homepage = "https://github.com/evilmartians/lefthook";
            license = pkgs.lib.licenses.mit;
            mainProgram = "lefthook";
          };
        };

        coreTools = with pkgs; [
          just
          git
          jq
          yq-go
          curl
          ripgrep # Deterministic Skylos grep verification
          gitleaks # Secret detection for git hooks
          lefthookPackage # Git hook manager
          util-linux # flock for environment locks
        ];

        pythonTools = with pkgs; [
          python
          uvPackage
          buf
          grpcurl
        ];

        frontendTools = with pkgs; [
          nodejs
          corepackPackage
          playwright-driver.browsers
        ];

        containerTools = with pkgs; [
          podman-compose
          dive
          skopeo
        ];

        infraTools = with pkgs; [
          kubectl
          kubernetes-helm
          helmfile
          k9s
          opentofu
          tflint
          azure-cli
          kustomize
        ];

        k8sTools = with pkgs; [
          kubectx
          stern
          fluxcd
        ];

        # Native libs for Python packages: asyncpg, argon2-cffi, grpcio, lxml, numpy
        nativeBuildDeps = with pkgs; [
          openssl
          openssl.dev
          zlib
          glib
          libffi
          libargon2
          libxml2
          libxslt
          postgresql.lib
          stdenv.cc.cc.lib
        ];

        baseEnv = {
          PYTHONDONTWRITEBYTECODE = "1";
          PYTHONUNBUFFERED = "1";
          UV_LINK_MODE = "copy";
          UV_PYTHON = "${python}/bin/python";
          PKG_CONFIG_PATH = pkgs.lib.makeSearchPath "lib/pkgconfig" nativeBuildDeps;
          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath nativeBuildDeps;
          OPENSSL_DIR = "${pkgs.openssl.dev}";
          OPENSSL_LIB_DIR = "${pkgs.openssl.out}/lib";
          OPENSSL_INCLUDE_DIR = "${pkgs.openssl.dev}/include";
        };

        # Explicit library path for numpy/grpcio wheels that need libstdc++
        libPath = pkgs.lib.makeLibraryPath nativeBuildDeps;

        baseHook = ''
          # Export LD_LIBRARY_PATH explicitly for subshells and uv run
          export LD_LIBRARY_PATH="${libPath}:$LD_LIBRARY_PATH"

          if ! scripts/dev/env-lock.sh exclusive venv -- sh -c '
            if [ ! -x ".venv/bin/python" ]; then
              uv venv --python ${python}/bin/python --quiet
            fi
          '; then
            echo "ERROR: unable to create the Python environment." >&2
            return 1
          fi
          source .venv/bin/activate

          if [ -f "uv.lock" ]; then
            if ! scripts/dev/env-lock.sh exclusive venv -- uv sync --all-packages --all-extras --no-extra cuda --group deadcode --locked; then
              echo "ERROR: uv sync --locked failed; refusing to use an incomplete environment." >&2
              return 1
            fi
          fi
        '';

        defaultHook = ''
          ${baseHook}

          if [ -f "pnpm-lock.yaml" ]; then
            if ! scripts/dev/env-lock.sh exclusive node_modules -- corepack pnpm install --frozen-lockfile --silent; then
              echo "ERROR: pnpm install failed; refusing to use an incomplete frontend environment." >&2
              return 1
            fi
          fi

          echo "Nohiki Dev Environment"
          echo "  Python ${python.version} | Node $(node --version) | pnpm $(corepack pnpm --version) | uv $(uv --version | cut -d' ' -f2)"
          echo "  Run 'just' for available commands"
        '';

      in
      {
        packages.lefthook = lefthookPackage;

        checks.lefthook-version = pkgs.runCommand "lefthook-version-${lefthookVersion}" { } ''
          actual="$(${lefthookPackage}/bin/lefthook version)"
          if [ "$actual" != "${lefthookVersion}" ]; then
            echo "expected Lefthook ${lefthookVersion}, got: $actual" >&2
            exit 1
          fi
          touch "$out"
        '';

        devShells.default = pkgs.mkShell {
          name = "nohiki";
          packages = coreTools ++ pythonTools ++ frontendTools ++ containerTools ++ infraTools;
          buildInputs = nativeBuildDeps;
          env = baseEnv // {
            PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
          };
          shellHook = defaultHook;
        };

        devShells.backend = pkgs.mkShell {
          name = "nohiki-backend";
          packages = coreTools ++ pythonTools;
          buildInputs = nativeBuildDeps;
          env = baseEnv;
          shellHook = ''
            ${baseHook}
            echo "Backend shell ready"
          '';
        };

        devShells.frontend = pkgs.mkShell {
          name = "nohiki-frontend";
          packages = coreTools ++ frontendTools;
          env = {
            PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
          };
          shellHook = ''
            if [ -f "pnpm-lock.yaml" ]; then
              corepack pnpm install --frozen-lockfile --silent
            fi
            echo "Frontend shell ready (Playwright browsers at $PLAYWRIGHT_BROWSERS_PATH)"
          '';
        };

        devShells.infra = pkgs.mkShell {
          name = "nohiki-infra";
          packages = coreTools ++ containerTools ++ infraTools ++ [ python ];
          shellHook = "echo 'Infrastructure shell ready'";
        };

        # Kubernetes tooling for working against any cluster you point KUBECONFIG
        # at (local or remote). This shell provisions nothing: it installs client
        # tools only and never touches system state.
        devShells.k8s = pkgs.mkShell {
          name = "nohiki-k8s";
          packages = coreTools ++ containerTools ++ infraTools ++ k8sTools ++ [ python ];
          shellHook = ''
            echo "k8s shell ready (kubectl, helm, kustomize, k9s, kubectx, stern, flux)"
            if [ -n "''${KUBECONFIG:-}" ]; then
              echo "  KUBECONFIG=$KUBECONFIG"
            else
              echo "  KUBECONFIG unset; kubectl uses ~/.kube/config. Point it at your cluster."
            fi
          '';
        };

        devShells.ci = pkgs.mkShell {
          name = "nohiki-ci";
          packages = [ python uvPackage nodejs corepackPackage pkgs.just pkgs.git pkgs.ripgrep pkgs.age pkgs.sops pkgs.kubernetes-helm pkgs.kubectl pkgs.kustomize pkgs.podman-compose pkgs.gitleaks pkgs.actionlint pkgs.hadolint pkgs.buf pkgs.skopeo lefthookPackage ];
          buildInputs = nativeBuildDeps;
          env = baseEnv;
        };

        formatter = pkgs.nixpkgs-fmt;
      }
    );
}
