export PATH := /Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$(PATH)
SHELL := /bin/bash

.PHONY: up down

up:
	@export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH"; docker compose up --build -d

down:
	@export PATH="/Applications/Docker.app/Contents/Resources/bin:$$PATH"; docker compose down
