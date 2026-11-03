{
  description = "Queued video recipe importer for self-hosted Mealie";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python3.withPackages (ps: [ ps.flask ]);
        in {
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "family-recipe-importer";
            version = "0.1.0";
            src = self;
            dontConfigure = true;
            dontBuild = true;
            installPhase = ''
              mkdir -p $out/lib/family-recipe-importer $out/bin
              cp recipe_queue.py queue_api.py video_worker.py $out/lib/family-recipe-importer/
              makeWrapper ${python}/bin/python $out/bin/recipe-queue-api \
                --add-flags "$out/lib/family-recipe-importer/queue_api.py"
              makeWrapper ${python}/bin/python $out/bin/recipe-video-worker \
                --add-flags "$out/lib/family-recipe-importer/video_worker.py" \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.yt-dlp ]}
            '';
            nativeBuildInputs = [ pkgs.makeWrapper ];
          };
        });

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.familyRecipeImporter;
        in {
          options.services.familyRecipeImporter = {
            enable = lib.mkEnableOption "the family recipe importer queue";
            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.system}.default;
              description = "Family recipe importer package.";
            };
            host = lib.mkOption {
              type = lib.types.str;
              default = "127.0.0.1";
              description = "Address on which the queue API listens.";
            };
            port = lib.mkOption {
              type = lib.types.port;
              default = 8088;
            };
            dataDir = lib.mkOption {
              type = lib.types.path;
              default = "/var/lib/family-recipe-importer";
            };
            environmentFile = lib.mkOption {
              type = lib.types.nullOr lib.types.path;
              default = null;
              description = "Environment file containing QUEUE_TOKEN.";
            };
            openFirewall = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Open the queue port in the host firewall.";
            };
          };

          config = lib.mkIf cfg.enable {
            networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
            systemd.services.family-recipe-importer-queue = {
              description = "Family recipe importer queue API";
              wantedBy = [ "multi-user.target" ];
              after = [ "network-online.target" ];
              wants = [ "network-online.target" ];
              environment = {
                HOST = cfg.host;
                PORT = toString cfg.port;
                QUEUE_DB = "${cfg.dataDir}/queue.db";
              };
              serviceConfig = {
                ExecStart = "${cfg.package}/bin/recipe-queue-api";
                DynamicUser = true;
                StateDirectory = baseNameOf cfg.dataDir;
                WorkingDirectory = cfg.dataDir;
                Restart = "on-failure";
                RestartSec = 5;
                NoNewPrivileges = true;
                PrivateTmp = true;
                ProtectSystem = "strict";
                ProtectHome = true;
              } // lib.optionalAttrs (cfg.environmentFile != null) {
                EnvironmentFile = cfg.environmentFile;
                ConditionPathExists = cfg.environmentFile;
              };
            };
          };
        };
    };
}
