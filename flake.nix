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
        uvConfig = builtins.fromTOML (builtins.readFile ./toolchain/uv.toml);
        uvVersion =
          let
            value = uvConfig.required-version;
          in
          if builtins.match "[0-9]+\\.[0-9]+\\.[0-9]+" value != null then
            value
          else
            throw "toolchain/uv.toml required-version must be an exact semantic version";
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
          version = uvVersion;
          src = pkgs.fetchurl {
            url = "https://github.com/astral-sh/uv/releases/download/${uvVersion}/uv-${uvRelease.target}.tar.gz";
            inherit (uvRelease) sha256;
          };
          sourceRoot = "uv-${uvRelease.target}";
          installPhase = ''
            mkdir -p "$out/bin"
            install -m755 uv uvx "$out/bin/"
          '';
        };

        releasePlatform = {
          x86_64-linux = {
            os = "linux";
            arch = "amd64";
            kindSha256 = "50030de23cf40a18505f20426f6a8506bedf13c6e509244bd1fa9463721b0f54";
            fluxSha256 = "4092b367fd060097976fb7261601f79420ecf7266328417dfd8dfee27de0e6a3";
            fluxOperatorSha256 = "67a9dad35c06ad76a298b6a28440022be0e2db3b93ef96dd090b4eaa77f542f7";
          };
          aarch64-linux = {
            os = "linux";
            arch = "arm64";
            kindSha256 = "b92cd615e97585de8ddade28ed5cd7feb4248d717c233eea5b03c37298900f5d";
            fluxSha256 = "665bfe5aeb843faf907e7f77250c31840499ff2dc65a64c2479409e3728748d1";
            fluxOperatorSha256 = "228380fdee63c310634eef11da2319641a2d42deb5464a3456a5113cbd5325f4";
          };
          x86_64-darwin = {
            os = "darwin";
            arch = "amd64";
            kindSha256 = "295ac6d0d634c9819c9907df45e3017d1f13166bd13c3404c45e79f7faa47498";
            fluxSha256 = "e4583db32e4f4f4ec195084f0381c704e5104a55a7ec4c1a444396137ecdb161";
            fluxOperatorSha256 = "b9c44e55b51a57565239e702bdc65fe6f7a38b632cbfa553716fc921d89e6e66";
          };
          aarch64-darwin = {
            os = "darwin";
            arch = "arm64";
            kindSha256 = "dca67911095a110c2b5c36e26df6cac860c602033e456c0db47be498cdef1ebb";
            fluxSha256 = "1dd6791738b1c250748c24c24b48e92908881596f999ad8bf10f84763d66fdb3";
            fluxOperatorSha256 = "90094f17601e536b7087147137f27b0cd0bfdf81aa33c2e12c20d22fc7d8889b";
          };
        }.${system};

        kindVersion = "0.32.0";
        kindPackage = pkgs.stdenvNoCC.mkDerivation {
          pname = "kind";
          version = kindVersion;
          src = pkgs.fetchurl {
            url = "https://github.com/kubernetes-sigs/kind/releases/download/v${kindVersion}/kind-${releasePlatform.os}-${releasePlatform.arch}";
            sha256 = releasePlatform.kindSha256;
          };
          dontUnpack = true;
          installPhase = ''
            mkdir -p "$out/bin"
            install -m755 "$src" "$out/bin/kind"
          '';
        };

        mkTarCli = { pname, version, owner, repo, asset, binary, sha256 }:
          pkgs.stdenvNoCC.mkDerivation {
            inherit pname version;
            src = pkgs.fetchurl {
              url = "https://github.com/${owner}/${repo}/releases/download/v${version}/${asset}";
              inherit sha256;
            };
            sourceRoot = "source";
            unpackPhase = ''
              mkdir source
              tar -xzf "$src" -C source
            '';
            installPhase = ''
              mkdir -p "$out/bin"
              install -m755 "${binary}" "$out/bin/${binary}"
            '';
          };

        fluxVersion = "2.9.2";
        fluxPackage = mkTarCli {
          pname = "flux";
          version = fluxVersion;
          owner = "fluxcd";
          repo = "flux2";
          asset = "flux_${fluxVersion}_${releasePlatform.os}_${releasePlatform.arch}.tar.gz";
          binary = "flux";
          sha256 = releasePlatform.fluxSha256;
        };

        fluxOperatorVersion = "0.55.0";
        fluxOperatorPackage = mkTarCli {
          pname = "flux-operator";
          version = fluxOperatorVersion;
          owner = "controlplaneio-fluxcd";
          repo = "flux-operator";
          asset = "flux-operator_${fluxOperatorVersion}_${releasePlatform.os}_${releasePlatform.arch}.tar.gz";
          binary = "flux-operator";
          sha256 = releasePlatform.fluxOperatorSha256;
        };

        pnpmPackage = pkgs.stdenvNoCC.mkDerivation {
          pname = "pnpm";
          version = "11.17.0";
          src = pkgs.fetchurl {
            url = "https://registry.npmjs.org/pnpm/-/pnpm-11.17.0.tgz";
            hash = "sha512-zKPOozKtJUu4QUX5ZtGfSHlhUhA0b8kseaBH8joNezzKPDeS8AdrofGDHSd++88KkRmzGppg7Kf7PWIx8zHvcg==";
          };
          sourceRoot = "package";
          nativeBuildInputs = [ pkgs.makeWrapper ];
          installPhase = ''
            mkdir -p "$out/bin" "$out/lib/pnpm"
            cp -R . "$out/lib/pnpm/"
            makeWrapper ${nodejs}/bin/node "$out/bin/pnpm" \
              --add-flags "$out/lib/pnpm/bin/pnpm.mjs"
            ln -s pnpm "$out/bin/pn"
            ln -s pnpm "$out/bin/pnpx"
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
          k6
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
          kindPackage
          fluxPackage
          fluxOperatorPackage
        ] ++ lib.optionals stdenv.isLinux [
          podman
          conmon
          crun
          fuse-overlayfs
          slirp4netns
          netavark
          aardvark-dns
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

        mkCiPrepare = commands: pkgs.writeShellScriptBin "ci-prepare" ''
          set -eu
          ${commands}
        '';
        ciPythonPrepare = mkCiPrepare ''
          exec scripts/dev/sync-ci-environment.sh
        '';
        ciNodePrepare = mkCiPrepare ''
          exec scripts/dev/sync-ci-node-environment.sh
        '';
        ciPolicyPrepare = mkCiPrepare ''
          exec scripts/dev/sync-ci-policy-environment.sh
        '';
        ciHygienePrepare = mkCiPrepare ''
          scripts/dev/sync-ci-environment.sh
          exec scripts/dev/sync-ci-node-environment.sh
        '';

        ciPythonTools = [
          python
          uvPackage
          pkgs.git
        ];
        ciNodeTools = [
          nodejs
          pnpmPackage
          pkgs.git
        ];
        ciPolicyTools = ciPythonTools ++ [
          pkgs.just
          pkgs.jq
          pkgs.yq-go
          pkgs.actionlint
          pkgs.check-jsonschema
          pkgs.hadolint
          pkgs.buf
          lefthookPackage
        ];
        # The selected Python surface includes CI contract tests that execute
        # the pinned repository validators, not just Python packages.
        ciTestTools = ciPolicyTools ++ [
          pkgs.openssh
          pkgs.ripgrep
          pkgs.age
          pkgs.sops
          pkgs.kubectl
          pkgs.kustomize
          pkgs.kubernetes-helm
          pkgs.podman-compose
          pkgs.gitleaks
          pkgs.skopeo
        ];
        ciHygieneTools = ciTestTools ++ ciNodeTools;
        ciTools = pkgs.lib.unique ciHygieneTools;

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
            if ! scripts/dev/env-lock.sh exclusive node_modules -- env CI=true LEFTHOOK=0 corepack pnpm install --frozen-lockfile --silent; then
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
              env CI=true LEFTHOOK=0 corepack pnpm install --frozen-lockfile --silent
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
            echo "k8s shell ready (kubectl, helm, kustomize, k9s, kubectx, stern, kind, flux, flux-operator, rootless Podman)"
            if [ -n "''${KUBECONFIG:-}" ]; then
              echo "  KUBECONFIG=$KUBECONFIG"
            else
              echo "  KUBECONFIG unset; kubectl uses ~/.kube/config. Point it at your cluster."
            fi
          '';
        };

        devShells.ci = pkgs.mkShell {
          name = "nohiki-ci";
          packages = ciTools ++ [ ciHygienePrepare ];
          buildInputs = nativeBuildDeps;
          env = baseEnv // {
            COREPACK_ENABLE_NETWORK = "0";
            UV_PYTHON_DOWNLOADS = "never";
          };
        };

        devShells.ci-python = pkgs.mkShell {
          name = "nohiki-ci-python";
          packages = ciTestTools ++ [ ciPythonPrepare ];
          buildInputs = nativeBuildDeps;
          env = baseEnv // {
            UV_PYTHON_DOWNLOADS = "never";
          };
        };

        devShells.ci-node = pkgs.mkShell {
          name = "nohiki-ci-node";
          packages = ciNodeTools ++ [ ciNodePrepare ];
          env = {
            COREPACK_ENABLE_NETWORK = "0";
          };
        };

        devShells.ci-policy = pkgs.mkShell {
          name = "nohiki-ci-policy";
          packages = ciPolicyTools ++ [ ciPolicyPrepare ];
          env = {
            PYTHONDONTWRITEBYTECODE = "1";
            PYTHONUNBUFFERED = "1";
            UV_LINK_MODE = "copy";
            UV_PYTHON = "${python}/bin/python";
            UV_PYTHON_DOWNLOADS = "never";
          };
        };

        devShells.ci-hygiene = pkgs.mkShell {
          name = "nohiki-ci-hygiene";
          packages = ciHygieneTools ++ [ ciHygienePrepare ];
          buildInputs = nativeBuildDeps;
          env = baseEnv // {
            COREPACK_ENABLE_NETWORK = "0";
            UV_PYTHON_DOWNLOADS = "never";
          };
        };

        formatter = pkgs.nixpkgs-fmt;
      }
    );
}
