from __future__ import annotations

from datetime import datetime
from typing import Any


def render_operational_report(summary: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    ts = generated_at or datetime.now().astimezone()
    classes = summary.get("operator_classes") or {}
    lines = [
        "# MEMORIA-PERMANENTE — RELATÓRIO OPERACIONAL",
        "",
        f"**Gerado em:** {ts.isoformat()}",
        f"**Health:** {summary.get('health', 'UNKNOWN')}",
        "",
        "## Visão geral",
        "",
        f"- Memórias totais: {summary.get('memories_total', 0)}",
        f"- Permanentes: {classes.get('PERMANENTE', 0)}",
        f"- Ativas: {classes.get('ATIVA', 0)}",
        f"- Arquivadas: {classes.get('ARQUIVADA', 0)}",
        f"- Descartáveis: {classes.get('DESCARTÁVEL', 0)}",
        f"- Protegidas: {classes.get('PROTEGIDA', 0)}",
        "",
        "## Aprendizado e ativação",
        "",
        f"- Aprendizados/procedimentos registrados: {summary.get('learning_items', 0)}",
        f"- Recuperações: {summary.get('retrievals', 0)}",
        f"- Aplicações: {summary.get('applications', 0)}",
        f"- Aplicações com sucesso: {summary.get('successes', 0)}",
        f"- Falhas: {summary.get('failures', 0)}",
        f"- Taxa de sucesso de reutilização: {summary.get('reuse_success_rate', 'N/A')}",
        "",
        "## Governança",
        "",
        f"- Conflitos conhecidos: {summary.get('conflicts', 0)}",
        f"- Eventos de auditoria: {summary.get('audit_events', 0)}",
        f"- Purge direto habilitado: {summary.get('purge_direct_enabled', False)}",
        "",
        "## Regra de descarte",
        "",
        "`DESCARTÁVEL` significa `DELETE_ELIGIBLE`. Não significa exclusão imediata.",
        "Purge exige verificação de referências, ausência de hold aplicável, quarentena e auditoria.",
        "",
        "---",
        "",
        "`PAINEL_OPERATIONAL_GATE = IN_PROGRESS`",
    ]
    return "\n".join(lines) + "\n"
