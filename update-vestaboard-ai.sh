cd /home/7d104f79c8624680859b88d6b18ae076/docker/vestaboard-ai
git pull                     # once the branch is pushed/merged
docker compose up -d --build # rebuild image + recreate changed containers
