.PHONY: up down test key logs bump-ytdlp

up:            ## start api + worker + redis
	docker compose up -d --build

down:
	docker compose down

test:
	pip install -r requirements-dev.txt && pytest -q

key:           ## make key NAME=alice
	docker compose exec api python -m scripts.manage_keys create --name $(NAME)

logs:
	docker compose logs -f api worker

bump-ytdlp:    ## one-command yt-dlp upgrade: make bump-ytdlp V=2026.11.01
	sed -i.bak -E 's/^yt-dlp\[default\]==.*/yt-dlp[default]==$(V)/' requirements.txt && rm -f requirements.txt.bak
	docker compose build --no-cache api worker && docker compose up -d
