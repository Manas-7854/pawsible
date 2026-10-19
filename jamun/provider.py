import threading
import re

from google import genai
from google.genai import types

from .storage import Store


SYSTEM_INSTRUCTION = (
    "You are a helpful everyday assistant. Keep answers short by default and friendly without excessive roleplay. "
    "You have no live web search. Never claim you searched the web. Use task functions only for tasks; "
    "when a task reference is ambiguous, ask a short clarification instead of guessing an ID. "
    "Only report a task change after the function result confirms success."
)

TASK_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(name="add_task", description="Add a new todo task.", parameters={"type": "OBJECT", "properties": {"title": {"type": "STRING"}, "notes": {"type": "STRING"}, "due_date": {"type": "STRING", "description": "YYYY-MM-DD, if given"}}, "required": ["title"]}),
    types.FunctionDeclaration(name="list_tasks", description="List tasks and their stable IDs.", parameters={"type": "OBJECT", "properties": {"status": {"type": "STRING", "description": "open, done, or all"}}}),
    types.FunctionDeclaration(name="update_task", description="Update a task by its known numeric ID.", parameters={"type": "OBJECT", "properties": {"task_id": {"type": "INTEGER"}, "title": {"type": "STRING"}, "notes": {"type": "STRING"}, "due_date": {"type": "STRING", "description": "YYYY-MM-DD"}, "status": {"type": "STRING"}}, "required": ["task_id"]}),
    types.FunctionDeclaration(name="complete_task", description="Mark a task done by its known numeric ID.", parameters={"type": "OBJECT", "properties": {"task_id": {"type": "INTEGER"}}, "required": ["task_id"]}),
])


def relevant_context(messages, max_chars=14000):
    selected = []
    remaining = max_chars
    for message in reversed(messages):
        content = message["content"]
        if message["status"] != "complete" or not content:
            continue
        if len(content) > remaining:
            if not selected:
                content = content[-remaining:]
            else:
                break
        selected.append(types.Content(role="user" if message["role"] == "user" else "model", parts=[types.Part.from_text(text=content)]))
        remaining -= len(content)
        if remaining <= 0:
            break
    return list(reversed(selected))


def execute_task_call(store, name, args, user_text=""):
    try:
        if name == "list_tasks":
            status = args.get("status", "all")
            if status not in ("all", "open", "done"):
                raise ValueError("Status must be all, open, or done")
            return {"tasks": [dict(row) for row in store.tasks(None if status == "all" else status)]}
        if name == "add_task":
            if set(args) - {"title", "notes", "due_date"}:
                raise ValueError("Unexpected argument")
            ident = store.add_task(args["title"], args.get("notes", ""), args.get("due_date"))
            return {"success": True, "task_id": ident}
        if name in ("update_task", "complete_task"):
            ident = args["task_id"]
            if type(ident) is not int or ident < 1:
                raise ValueError("A valid numeric task ID is required")
            target = next((row for row in store.tasks() if row["id"] == ident), None)
            if target is None:
                raise ValueError(f"Task #{ident} does not exist. Ask which task the user means.")
            duplicate_titles = [row for row in store.tasks() if row["title"].casefold() == target["title"].casefold()]
            if len(duplicate_titles) > 1 and user_text and not re.search(rf"(?<!\d)#?{ident}(?!\d)", user_text):
                raise ValueError("Multiple tasks have this title. Ask the user for the task ID.")
            if name == "complete_task":
                if set(args) != {"task_id"}:
                    raise ValueError("Unexpected argument")
                store.complete_task(ident)
            else:
                if set(args) - {"task_id", "title", "notes", "due_date", "status"}:
                    raise ValueError("Unexpected argument")
                store.update_task(ident, **{key: value for key, value in args.items() if key != "task_id"})
            return {"success": True, "task_id": ident}
        raise ValueError("Unsupported function")
    except (KeyError, TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}


class GeminiProvider:
    def __init__(self, api_key, model, db_path):
        self.api_key = api_key
        self.model = model
        self.db_path = db_path
        self.approve_task_change = None

    def stream(self, messages, memories, tasks, on_text, stopped: threading.Event):
        if not self.api_key:
            raise RuntimeError("No API key. Set GEMINI_API_KEY in your environment or the project .env file, then restart jamun.")
        client = genai.Client(api_key=self.api_key, http_options=types.HttpOptions(timeout=30000))
        store = Store(self.db_path)
        try:
            contents = relevant_context(messages)
            user_text = next((row["content"] for row in reversed(messages) if row["role"] == "user"), "")
            memory_text = "\n".join(f"- {row['content']}" for row in memories[:20])[:2500]
            task_text = "\n".join(f"#{row['id']} {row['title']} ({row['status']})" for row in tasks[:30])[:2000]
            instruction = SYSTEM_INSTRUCTION
            if memory_text:
                instruction += "\nExplicitly saved user preferences:\n" + memory_text
            if task_text:
                instruction += "\nCurrent tasks (IDs are authoritative):\n" + task_text
            config = types.GenerateContentConfig(
                system_instruction=instruction,
                tools=[TASK_TOOLS],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            changes_done = 0
            for _ in range(4):
                if stopped.is_set():
                    return
                calls = []
                model_parts = []
                text_started = False
                for attempt in range(3):
                    try:
                        stream = client.models.generate_content_stream(model=self.model, contents=contents, config=config)
                        for chunk in stream:
                            if stopped.is_set():
                                return
                            parts = chunk.candidates[0].content.parts if chunk.candidates and chunk.candidates[0].content else []
                            for part in parts:
                                model_parts.append(part)
                                if part.text:
                                    text_started = True
                                    on_text(part.text)
                                if part.function_call:
                                    calls.append(part.function_call)
                        break
                    except Exception as exc:
                        code = getattr(exc, "code", None)
                        if text_started or attempt == 2 or code not in (429, 500, 502, 503, 504, None):
                            if changes_done:
                                on_text("\nThe task change was saved, but Gemini could not finish the reply.")
                                return
                            if code == 429:
                                raise RuntimeError("Gemini quota or rate limit reached. Try again later.") from None
                            if code in (401, 403):
                                raise RuntimeError("Gemini rejected the API key or project access.") from None
                            if code == 404:
                                raise RuntimeError("The configured Gemini model is unavailable. Change it in Settings.") from None
                            raise RuntimeError(f"Gemini is offline or returned an error ({type(exc).__name__}, code {code}). Check the connection and model, then retry.") from None
                        if stopped.wait(0.7 * (2 ** attempt)):
                            return
                if not calls:
                    return
                contents.append(types.Content(role="model", parts=model_parts))
                replies = []
                for call in calls:
                    args = dict(call.args or {})
                    if call.name in {"add_task", "update_task", "complete_task"} and not (
                        self.approve_task_change and self.approve_task_change(call.name, args)
                    ):
                        result = {"success": False, "error": "The user did not approve this task change."}
                    else:
                        result = execute_task_call(store, call.name, args, user_text)
                    if result.get("success") is True:
                        changes_done += 1
                    replies.append(types.Part.from_function_response(name=call.name, response=result))
                contents.append(types.Content(role="user", parts=replies))
            on_text("\nI reached the task-operation limit. Please try a shorter request.")
        finally:
            store.db.close()
            client.close()
