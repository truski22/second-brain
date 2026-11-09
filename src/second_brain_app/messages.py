"""Spanish texts for the harness runtime; the harness itself is language-neutral."""
from tenet_harness.contracts import Messages

SPANISH = Messages(
    empty_message="El mensaje está vacío.",
    idempotency_conflict="La clave de solicitud ya se utilizó con otro mensaje.",
    other_agent="La conversación pertenece a otro agente.",
    busy="Ya hay una respuesta en curso.",
    wait_for_run="Espera a que termine la respuesta.",
    run_failed="No se pudo completar la respuesta. Comprueba Ollama y los límites de ejecución.",
    cancelled="Detenido. Las acciones ya realizadas se conservan.",
    memory_queue_full="Memoria no guardada: cola llena.",
    memory_failed="No se pudo guardar la memoria de este mensaje.",
)
