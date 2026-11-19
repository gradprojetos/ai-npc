import os
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent / "outputs"


def log_test_turn(filename: str, turn_title: str, user: str, message: str, reply: str) -> None:
    """Registra uma interação de turno em um arquivo de log local para inspeção e regressão."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUTS_DIR / filename
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"=== {turn_title} ===\n")
        f.write(f"[{user}]: {message}\n")
        f.write(f"[SISTEMA / LOOMIS]:\n{reply}\n\n")


def clear_test_output(filename: str) -> None:
    """Limpa o arquivo de saída antes de iniciar o teste."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUTS_DIR / filename
    if filepath.exists():
        filepath.unlink()
