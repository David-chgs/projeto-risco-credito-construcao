from __future__ import annotations

import time

import requests


URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.21854/dados"

PARAMS = {
    "formato": "json",
    "dataInicial": "01/01/2023",
    "dataFinal": "31/12/2024",
}

TIMEOUTS_TO_TEST = [10, 20, 30, 45, 60, 90, 120]


def main() -> None:
    for timeout in TIMEOUTS_TO_TEST:
        print(f"\nTesting timeout={timeout}s")

        start_time = time.perf_counter()

        try:
            response = requests.get(
                URL,
                params=PARAMS,
                timeout=timeout,
            )
            elapsed_time = time.perf_counter() - start_time

            response.raise_for_status()
            data = response.json()

            print(f"SUCCESS | timeout={timeout}s | elapsed={elapsed_time:.2f}s | rows={len(data)}")
            break

        except requests.exceptions.Timeout:
            elapsed_time = time.perf_counter() - start_time
            print(f"TIMEOUT | timeout={timeout}s | elapsed={elapsed_time:.2f}s")

        except requests.exceptions.RequestException as error:
            elapsed_time = time.perf_counter() - start_time
            print(f"REQUEST ERROR | timeout={timeout}s | elapsed={elapsed_time:.2f}s | error={error}")
            break

        except ValueError as error:
            elapsed_time = time.perf_counter() - start_time
            print(f"JSON ERROR | timeout={timeout}s | elapsed={elapsed_time:.2f}s | error={error}")
            break


if __name__ == "__main__":
    main()
