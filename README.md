# JARVIS WebUI Advanced

Versión funcional inicial:
- Panel web
- Proveedor OpenAI-compatible
- Descubrimiento automático GET /v1/models
- Chat POST /v1/chat/completions
- Failover secuencial automático entre modelos
- Orden/prioridad de modelos
- API keys guardadas solo en el backend
- Logs básicos en UI
- Persistencia en /data

## Coolify
Crea una aplicación desde este proyecto/Dockerfile, expón el puerto 8080 y asigna tu dominio.
Después abre Proveedores, añade la Base URL terminada en /v1 y tu API key.

## Importante
Memory, Skills, Tools y Automations aparecen como módulos preparados, pero requieren los endpoints reales de Hermes para ser funcionales.
El chat actual usa directamente el proveedor configurado; la siguiente integración puede enrutar las conversaciones a Hermes para conservar su comportamiento de agente.
