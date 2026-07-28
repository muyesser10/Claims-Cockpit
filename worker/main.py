import time


def main():
    # Keep the worker process alive until the Redis queue consumer pipeline is implemented
    while True:
        time.sleep(10)


if __name__ == "__main__":
    main()
