export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=ap-south-1

install:
	@./prepare.sh

up:
	docker-compose -f ./docker-compose.yml up -d

generate:
	./dist/message-generators/windows.exe

build:
	docker build -t etl-pipeline .

run:
	docker run --network host etl-pipeline

all: install up generate build run
	