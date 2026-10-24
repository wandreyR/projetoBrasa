"""Horário de funcionamento e pausa de pedidos."""
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from .tempo import agora_local

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
CHAVE_PAUSA = "pedidos_pausados"


def pedidos_pausados(db: Session) -> bool:
    cfg = db.get(models.Configuracao, CHAVE_PAUSA)
    return bool(cfg and cfg.valor == "1")


def definir_pausa(db: Session, pausado: bool):
    cfg = db.get(models.Configuracao, CHAVE_PAUSA)
    if not cfg:
        cfg = models.Configuracao(chave=CHAVE_PAUSA)
        db.add(cfg)
    cfg.valor = "1" if pausado else "0"


def _janela(h: models.HorarioFuncionamento, dia: date) -> Optional[tuple]:
    """Início e fim do expediente que começa em `dia` (o fim pode cair no dia seguinte)."""
    if h is None or h.fechado:
        return None
    inicio = datetime.combine(dia, h.abre)
    fim = datetime.combine(dia, h.fecha)
    if h.fecha == time(23, 59):
        fim = datetime.combine(dia + timedelta(days=1), time(0, 0))  # "até 23:59" = até a meia-noite
    elif fim <= inicio:
        fim += timedelta(days=1)  # passa da meia-noite (ex.: 18:00 às 01:00)
    return inicio, fim


def _proxima_abertura(horarios: dict, agora: datetime) -> Optional[datetime]:
    for d in range(0, 8):
        dia = agora.date() + timedelta(days=d)
        janela = _janela(horarios.get(dia.weekday()), dia)
        if janela and janela[0] > agora:
            return janela[0]
    return None


def _texto_quando(momento: datetime, agora: datetime) -> str:
    hora = momento.strftime("%H:%M")
    dias = (momento.date() - agora.date()).days
    if dias == 0:
        return f"hoje às {hora}"
    if dias == 1:
        return f"amanhã às {hora}"
    return f"{DIAS[momento.weekday()]} às {hora}"


def status_loja(db: Session, agora: Optional[datetime] = None) -> dict:
    agora = agora or agora_local()
    horarios = {h.dia_semana: h for h in db.query(models.HorarioFuncionamento)}
    em_horario = False
    fecha_em = None
    # expediente de hoje ou o de ontem que atravessou a meia-noite
    for dia in (agora.date(), agora.date() - timedelta(days=1)):
        janela = _janela(horarios.get(dia.weekday()), dia)
        if janela and janela[0] <= agora < janela[1]:
            em_horario, fecha_em = True, janela[1]
            break
    # sem nenhum horário cadastrado: não bloqueia (instalação nova)
    if not horarios:
        em_horario = True

    pausado = pedidos_pausados(db)
    if pausado:
        mensagem = "Pedidos pausados no momento pela cozinha. Tente novamente em alguns minutos."
    elif not em_horario:
        proxima = _proxima_abertura(horarios, agora)
        mensagem = "Estamos fechados agora." + (f" Abrimos {_texto_quando(proxima, agora)}." if proxima else "")
    else:
        ate = (fecha_em - timedelta(minutes=1)) if fecha_em and fecha_em.time() == time(0, 0) else fecha_em
        mensagem = f"Aberto — recebendo pedidos até as {ate.strftime('%H:%M')}." if ate else "Aberto"
    return {"aberto": em_horario and not pausado, "pausado": pausado, "em_horario": em_horario, "mensagem": mensagem}
