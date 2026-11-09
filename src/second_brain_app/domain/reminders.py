from uuid import uuid4

from tenet_harness.storage import Store, timestamp

from .clock import Clock


class Reminders:
    def __init__(self, store: Store, clock: Clock):
        self.store = store
        self.clock = clock
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY,task TEXT NOT NULL,due TEXT,"
                "due_date TEXT,created_at TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS reminder_actions (key TEXT PRIMARY KEY, result TEXT NOT NULL)")

    def pending(self, expression: str = ""):
        target = self.clock.resolve(expression) if expression else None
        with self.store.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,task,due,due_date,created_at FROM reminders WHERE done=0 "
                + ("AND due_date=? " if target else "")
                + "ORDER BY (due_date IS NULL),due_date,created_at",
                (target,) if target else (),
            )]

    def add(self, task: str, due: str, key: str):
        import json
        task = task.strip()
        if not task or len(task) > 1000:
            raise ValueError("La tarea debe contener entre 1 y 1000 caracteres.")
        date = self.clock.resolve(due)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = db.execute("SELECT result FROM reminder_actions WHERE key=?", (key,)).fetchone()
            if cached:
                return json.loads(cached[0])
            result = {"id": str(uuid4()), "task": task, "due_date": date}
            db.execute("INSERT INTO reminders VALUES (?,?,?,?,?,0)",
                       (result["id"], task, due, date, timestamp()))
            db.execute("INSERT INTO reminder_actions VALUES (?,?)", (key, json.dumps(result)))
            return result

    def complete(self, reminder_id: str):
        with self.store.connect() as db:
            row = db.execute("SELECT id,task,done FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            if not row:
                raise ValueError("No existe ese recordatorio. Consulta la lista y usa su ID completo.")
            db.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))
            return {"id": row["id"], "task": row["task"], "done": True}
