"""Conversão entre UTC (como as datas são gravadas no banco) e o horário local da pizzaria.

Usamos um deslocamento fixo em vez de zoneinfo porque a imagem python:slim não
traz a base de fusos, e o Brasil não tem horário de verão desde 2019.
"""
import os
from datetime import date, datetime, time, timedelta

FUSO_HORAS = int(os.getenv("FUSO_HORARIO_HORAS", "-3"))  # Brasília = UTC-3
_DESLOCAMENTO = timedelta(hours=FUSO_HORAS)


def agora_local() -> datetime:
    return datetime.utcnow() + _DESLOCAMENTO


def hoje_local() -> date:
    return agora_local().date()


def utc_para_local(momento_utc: datetime) -> datetime:
    return momento_utc + _DESLOCAMENTO


def inicio_do_dia_em_utc(dia: date) -> datetime:
    """00:00 do dia local, expresso em UTC (para comparar com colunas do banco)."""
    return datetime.combine(dia, time.min) - _DESLOCAMENTO
