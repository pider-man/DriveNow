"""Entry point for ``python -m drivenow.worker``: the RabbitMQ audit worker."""

from drivenow.messaging.worker import main

if __name__ == "__main__":
    main()
