# Memoria Permanente V4 - Conversation Capture

Componente de ingestao autorizado para Chrome/Edge. Nao usa Learning, Invisible Browser, screenshot, mouse ou teclado.

Fluxo: turno ChatGPT -> fila local da extensao -> POST /v1/conversation-ingestion/turn -> fila duravel V4 -> memoria/checkpoint/Context Pack.

Instalacao: abrir chrome://extensions ou edge://extensions, habilitar modo do desenvolvedor e carregar esta pasta como extensao sem compactacao. A ativacao exige acao explicita do operador por politica de seguranca do navegador.

A extensao captura somente paginas https://chatgpt.com/ que contenham /c/<conversation_id>. Mensagens sao enviadas apenas apos estabilidade do DOM por alguns segundos. Eventos nao entregues permanecem em chrome.storage.local e sao reenviados com backoff.
