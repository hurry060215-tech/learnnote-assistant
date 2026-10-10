from contextlib import ExitStack
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import assistant_operations as operations, assistant_operation_store as journal, storage
from app.assistant_operation_types import OperationRequest
from app.assistant_operation_planner import PlanRequest, plan
from app.models import TaskOptions
from app import library, knowledge, config, study, community
from app.routers import notes


class AssistantOperationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (journal, notes, storage, library, knowledge, config, study, community): self.stack.enter_context(patch.object(module, "DATA_DIR", self.root))
        self.stack.enter_context(patch.object(storage, "TASK_DIR", self.root / "tasks"))
        self.stack.enter_context(patch.object(storage, "ensure_dirs", lambda: None))
        self.task = storage.create_task("local", "Synthetic source")
        self.original = storage.task_dir(self.task.id) / "note.md"
        self.text = "# Original title\n\nPRIVATE_SYNTHETIC_SENTENCE\n\nTarget paragraph.\n"
        # Raw CRLF source bytes stay untouched; edition revisions cover normalized text.
        # Use explicit bytes so both Linux and Windows exercise this boundary.
        self.bytes = self.text.replace("\n", "\r\n").encode("utf-8")
        self.original.write_bytes(self.bytes)
        storage.update_task(self.task.id, status="success", note_path=str(self.original))
        self.source = {"kind": "task", "id": self.task.id, "revision": journal.digest(self.text)}

    def request(self, tool="edit_note", arguments=None, operation_id=None):
        return OperationRequest(operation_id=operation_id or uuid4().hex, source=self.source, tool=tool,
            arguments=arguments if arguments is not None else {"mode": "replace", "old_text": "Target paragraph.", "text": "Edited paragraph."})

    def edit(self):
        request = self.request(); prepared = operations.prepare(request)
        self.assertEqual(prepared["status"], "prepared")
        return operations.execute(request.operation_id)

    def current(self):
        return notes.get_edition("task", self.task.id)

    def test_preview_execution_replay_and_undo_preserve_original_bytes(self):
        request = self.request(); prepared = operations.prepare(request)
        self.assertIn("-Target paragraph.", prepared["preview"]["diff"])
        self.assertIn("Target paragraph.", self.current()["text"])
        completed = operations.execute(request.operation_id)
        self.assertEqual(completed["status"], "completed")
        self.assertIn("Edited paragraph.", self.current()["text"])
        self.assertEqual(operations.execute(request.operation_id), completed)
        undo_id = uuid4().hex
        undone = operations.undo(undo_id, request.operation_id)
        self.assertEqual(undone["status"], "completed")
        self.assertEqual(self.current()["text"], self.text)
        self.assertEqual(operations.undo(undo_id, request.operation_id), undone)
        self.assertEqual(self.original.read_bytes(), self.bytes)

    def test_changed_payload_same_id_and_later_edits_are_never_overwritten(self):
        request = self.request(); operations.prepare(request)
        with self.assertRaises(HTTPException) as error:
            operations.prepare(self.request(arguments={"mode": "append", "text": "other"}, operation_id=request.operation_id))
        self.assertEqual(error.exception.status_code, 409)
        notes.put_edition("task", self.task.id, notes.EditionRequest(text="Later manual work", revision=self.source["revision"]))
        result = operations.execute(request.operation_id)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.current()["text"], "Later manual work")

    def test_completed_replay_reports_history_without_reapplying_over_later_work(self):
        completed = self.edit()
        notes.put_edition("task", self.task.id, notes.EditionRequest(text="Later", revision=completed["result"]["revision"]))
        self.assertEqual(operations.execute(completed["id"])["status"], "completed")
        self.assertEqual(self.current()["text"], "Later")
        with self.assertRaises(HTTPException): operations.undo(uuid4().hex, completed["id"])
        self.assertEqual(self.current()["text"], "Later")

    def test_append_preserves_existing_trailing_whitespace_and_title_ignores_code(self):
        from app.assistant_note_tools import edit_text
        self.assertEqual(edit_text("before\n\n\n", {"mode": "append", "text": "after", "old_text": ""}), "before\n\n\nafter\n")
        text = "```md\n# Code title\n```\n# Real title\n"
        self.assertEqual(edit_text(text, {"mode": "set_title", "text": "New", "old_text": ""}), "```md\n# Code title\n```\n# New\n")
        with self.assertRaises(HTTPException): edit_text("twice twice", {"mode": "replace", "old_text": "twice", "text": "one"})

    def test_read_is_bounded_and_revision_bound(self):
        request = self.request("read_note", {"start_line": 3, "line_count": 1})
        operations.prepare(request); result = operations.execute(request.operation_id)
        self.assertEqual(result["result"]["text"], "PRIVATE_SYNTHETIC_SENTENCE")
        self.assertEqual(result["result"]["revision"], self.source["revision"])
        self.assertEqual(self.original.read_bytes(), self.bytes)

    def test_cancel_before_commit_survives_memory_loss(self):
        request = self.request(); operations.prepare(request)
        self.assertEqual(operations.cancel(request.operation_id)["status"], "cancelled")
        journal._cancelled.clear()
        self.assertEqual(operations.execute(request.operation_id)["status"], "cancelled")
        self.assertEqual(self.current()["text"], self.text)

    def test_cancel_after_the_actual_write_cannot_report_rollback(self):
        request = self.request(); operations.prepare(request)
        original_save = operations.save_edition_locked
        def write_then_cancel(*args):
            result = original_save(*args); journal.cancellation(request.operation_id).set(); return result
        with patch.object(operations, "save_edition_locked", side_effect=write_then_cancel):
            result = operations.execute(request.operation_id)
        self.assertEqual(result["status"], "completed")
        self.assertIn("Edited paragraph.", self.current()["text"])

    def test_cancel_during_export_leaves_no_published_artifact(self):
        from app.document_exports import DocumentExport
        request = self.request("export_note", {"format": "markdown"}); operations.prepare(request)
        started, release = threading.Event(), threading.Event(); result = {}
        def render(*args):
            started.set(); self.assertTrue(release.wait(5)); return DocumentExport(b"synthetic", "text/markdown", "md", "UTF-8")
        with patch.object(operations, "export_note", side_effect=render):
            worker = threading.Thread(target=lambda: result.update(operations.execute(request.operation_id)));worker.start()
            self.assertTrue(started.wait(5))
            canceller = threading.Thread(target=lambda: operations.cancel(request.operation_id));canceller.start()
            self.assertTrue(journal.cancellation(request.operation_id).wait(5));release.set()
            worker.join(5);canceller.join(5)
        self.assertFalse(worker.is_alive()); self.assertFalse(canceller.is_alive())
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse((journal.root() / (request.operation_id + ".md")).exists())

    def test_failed_receipt_after_commit_recovers_without_duplicate_mutation(self):
        request = self.request();operations.prepare(request)
        original_save = journal.save
        def fail_completed(value):
            if value["status"] == "completed": raise OSError("synthetic disk failure")
            return original_save(value)
        with patch.object(journal, "save", side_effect=fail_completed), patch.object(operations, "save_edition_locked", wraps=operations.save_edition_locked) as save:
            result = operations.execute(request.operation_id)
            self.assertEqual(result["status"], "completed")
            self.assertIn("回执暂未写入", result["receipt_warning"])
            self.assertEqual(save.call_count, 1)
        recovered = operations.get_operation(request.operation_id)
        self.assertEqual(recovered["status"], "completed");self.assertTrue(recovered["result"]["recovered"])
        with patch.object(operations, "save_edition_locked") as save:
            operations.execute(request.operation_id);save.assert_not_called()

    def test_failed_record_before_write_and_unknown_recovery_state_preserve_work(self):
        request = self.request()
        with patch.object(journal, "atomic_write_text", side_effect=OSError("synthetic path")):
            with self.assertRaises(HTTPException): operations.prepare(request)
        self.assertEqual(self.current()["text"], self.text)
        operations.prepare(request); value=journal.load(request.operation_id);value["status"]="running";journal.save(value)
        self.assertEqual(operations.get_operation(request.operation_id)["status"], "prepared")
        value["status"]="running";journal.save(value)
        notes.put_edition("task",self.task.id,notes.EditionRequest(text="Other edit",revision=self.source["revision"]))
        self.assertEqual(operations.get_operation(request.operation_id)["status"], "conflict")
        self.assertEqual(self.current()["text"], "Other edit")

    def test_actual_export_formats_use_personal_revision_and_verified_cached_bytes(self):
        completed=self.edit();self.source["revision"]=completed["result"]["revision"]
        for format in ("markdown","html","docx","pdf"):
            with self.subTest(format=format):
                request=self.request("export_note",{"format":format});operations.prepare(request)
                result=operations.execute(request.operation_id);self.assertEqual(result["status"],"completed",result)
                path,info=operations.artifact_path(request.operation_id);content=path.read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(),info["sha256"])
                if format=="docx":
                    from docx import Document
                    text="\n".join(p.text for p in Document(BytesIO(content)).paragraphs)
                elif format=="pdf":
                    from pypdf import PdfReader
                    text="\n".join(p.extract_text() for p in PdfReader(BytesIO(content)).pages)
                else:text=content.decode()
                self.assertIn("Edited paragraph.",text);self.assertNotIn("Target paragraph.",text)
                path.write_bytes(b"tampered")
                with self.assertRaises(HTTPException):operations.artifact_path(request.operation_id)

    def test_tampered_record_cannot_reference_an_arbitrary_file(self):
        request=self.request("export_note",{"format":"markdown"});operations.prepare(request);operations.execute(request.operation_id)
        path=journal.path_for(request.operation_id);value=json.loads(path.read_text(encoding="utf-8"))
        value["artifact"]["name"]="../../private.txt";path.write_text(json.dumps(value),encoding="utf-8")
        with self.assertRaises(HTTPException):operations.artifact_path(request.operation_id)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["artifact"]["name"],"../../private.txt")

    def test_api_rejects_unknown_tools_parameters_and_unconfirmed_write(self):
        from app.main import app
        client=TestClient(app);request=self.request();url="/api/assistant/operations"
        data=request.model_dump();data["arguments"]["shell"]="echo forbidden"
        self.assertEqual(client.post(url+"/prepare",json=data).status_code,422)
        data=request.model_dump();data["tool"]="shell"
        self.assertEqual(client.post(url+"/prepare",json=data).status_code,422)
        self.assertEqual(client.post(url+"/prepare",json=request.model_dump()).status_code,200)
        self.assertEqual(client.post(url+"/"+request.operation_id+"/execute",json={}).status_code,422)
        self.assertEqual(self.current()["text"],self.text)

    def model_response(self,name="export_note",arguments=None,calls=1):
        tool=SimpleNamespace(type="function",function=SimpleNamespace(name=name,arguments=json.dumps(arguments or {"format":"pdf"})))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls",message=SimpleNamespace(tool_calls=[tool]*calls,content=None))])

    def test_model_tool_call_is_validated_without_executing_and_shares_only_opted_in_text(self):
        request=PlanRequest(question="Export this note",source=self.source,options=TaskOptions(llm_base_url="http://127.0.0.1:1234/v1",llm_model="dummy"))
        with patch("openai.OpenAI") as constructor,patch("app.summarizer._compatible_completion",return_value=self.model_response()) as complete:
            result=plan(request);self.assertEqual(result["tool"],"export_note");self.assertFalse(result["executed"])
            payload=json.dumps(complete.call_args.kwargs["messages"]);self.assertNotIn("PRIVATE_SYNTHETIC_SENTENCE",payload)
            self.assertEqual(complete.call_args.kwargs["max_tokens"],3000)
            result=plan(request.model_copy(update={"share_source":True}))
            self.assertGreater(result["shared_characters"],0)
            self.assertIn("PRIVATE_SYNTHETIC_SENTENCE",json.dumps(complete.call_args.kwargs["messages"]))
        self.assertEqual(self.current()["text"],self.text)
        self.assertEqual(list(journal.root().glob("*.json")),[])

    def test_model_unknown_parallel_and_extra_parameter_calls_cannot_mutate(self):
        request=PlanRequest(question="Do something",source=self.source,options=TaskOptions(llm_base_url="http://127.0.0.1:1234/v1"))
        for response in (self.model_response("shell"),self.model_response(calls=2),self.model_response(arguments={"format":"pdf","path":"../escape"})):
            with patch("openai.OpenAI"),patch("app.summarizer._compatible_completion",return_value=response):
                with self.assertRaises(HTTPException) as error:plan(request)
                self.assertEqual(error.exception.status_code,502)
        self.assertEqual(self.current()["text"],self.text)

    def test_custom_endpoint_cannot_inherit_default_credential(self):
        request=PlanRequest(question="Set dark mode",options=TaskOptions(llm_base_url="https://custom.example.test/v1",llm_model="dummy"))
        with patch("app.assistant_operation_planner.LLM_API_KEY","DUMMY_DEFAULT"),patch("app.assistant_operation_planner.LLM_BASE_URL","https://default.example.test/v1"),patch("openai.OpenAI") as constructor:
            with self.assertRaises(HTTPException) as error:plan(request)
            self.assertEqual(error.exception.status_code,409);constructor.assert_not_called()

    def test_serialized_limit_rejects_preparation_before_creating_unreadable_record(self):
        text = "# Synthetic\n" + ("\\\\\\\n" * 240000)
        self.original.write_text(text, encoding="utf-8")
        self.source["revision"] = journal.digest(text)
        request = self.request(arguments={"mode":"append", "text":"Review appendix"})
        with self.assertRaises(HTTPException) as error:
            operations.prepare(request)
        self.assertEqual(error.exception.status_code, 422)
        self.assertIsNone(journal.load(request.operation_id))
        self.assertEqual(self.current()["text"], text)

    def test_full_reservation_retains_terminal_and_one_undo_capacity(self):
        # Two read slots + edit and its reserved undo exactly fill four slots.
        with patch.object(journal, "MAX_SLOTS", 4):
            for _ in range(2): operations.prepare(self.request("read_note", {}))
            request = self.request(); operations.prepare(request)
            with self.assertRaises(HTTPException): operations.prepare(self.request("read_note", {}))
            # Changing a global limit cannot consume already-reserved space.
            with patch.object(journal, "MAX_BYTES", 1):
                result = operations.execute(request.operation_id)
                self.assertEqual(result["status"], "completed")
                undo_id = uuid4().hex
                self.assertEqual(operations.undo(undo_id, request.operation_id)["status"], "completed")
                self.assertEqual(self.current()["text"], self.text)
                self.assertEqual(len(list(journal.root().glob("*.json"))), 4)
                with self.assertRaises(HTTPException): operations.undo(uuid4().hex, request.operation_id)
                with self.assertRaises(HTTPException): operations.undo(uuid4().hex, undo_id)

    def test_forget_requires_terminal_state_and_reclaims_pair_without_changing_note(self):
        request = self.request(); operations.prepare(request)
        with self.assertRaises(HTTPException): operations.forget(request.operation_id)
        operations.execute(request.operation_id)
        undo_id=uuid4().hex; operations.undo(undo_id,request.operation_id)
        self.assertTrue(operations.forget(undo_id)["deleted"])
        self.assertIsNone(journal.load(request.operation_id));self.assertIsNone(journal.load(undo_id))
        self.assertEqual(self.current()["text"],self.text)

    def test_deleting_task_removes_read_edit_undo_and_export_copies(self):
        edit = self.edit(); self.source["revision"] = edit["result"]["revision"]
        for tool, args in (("read_note", {}),("export_note", {"format":"markdown"})):
            request=self.request(tool,args);operations.prepare(request);operations.execute(request.operation_id)
        self.assertTrue(list(journal.root().glob("*.json")))
        storage.delete_task(self.task.id)
        self.assertFalse(list(journal.root().glob("*.json")))
        self.assertFalse(list(journal.root().glob("*.md")))
        with self.assertRaises(HTTPException):operations.get_operation(edit["id"])
        with self.assertRaises(HTTPException):operations.artifact_path(request.operation_id)

    def test_deleting_material_removes_assistant_copies_but_keeps_other_source(self):
        material=library.import_document_material("synthetic.md",b"# Material\nSynthetic private content")
        task_read=self.request("read_note",{});operations.prepare(task_read);operations.execute(task_read.operation_id)
        edition=notes.get_edition("material",material["material_id"])
        self.source={"kind":"material","id":material["material_id"],"revision":edition["revision"]}
        ids=[]
        for tool,args in (("read_note",{}),("export_note",{"format":"markdown"})):
            request=self.request(tool,args);operations.prepare(request);operations.execute(request.operation_id);ids.append(request.operation_id)
        library.delete_material(material["material_id"])
        self.assertEqual(operations.get_operation(task_read.operation_id)["status"],"completed")
        for operation_id in ids:
            with self.assertRaises(HTTPException):operations.get_operation(operation_id)
            self.assertFalse((journal.root()/(operation_id+".md")).exists())

    def test_corrupt_assistant_record_blocks_source_deletion_before_data_changes(self):
        request=self.request();operations.prepare(request)
        journal.path_for(request.operation_id).write_text("{damaged",encoding="utf-8")
        with self.assertRaises(HTTPException):storage.delete_task(self.task.id)
        self.assertEqual(self.original.read_bytes(),self.bytes)
        self.assertEqual(storage.get_task(self.task.id).id,self.task.id)

    def test_missing_source_blocks_access_but_keeps_copies_for_recovery(self):
        ids=[]
        for tool,args in (("read_note",{}),("export_note",{"format":"markdown"})):
            request=self.request(tool,args);operations.prepare(request);operations.execute(request.operation_id);ids.append(request.operation_id)
        original_metadata=storage.task_file(self.task.id).read_bytes()
        storage.task_file(self.task.id).unlink()  # Could be interrupted deletion OR lost metadata.
        with self.assertRaises(HTTPException) as error: operations.get_operation(ids[0])
        self.assertEqual(error.exception.status_code,404)
        with self.assertRaises(HTTPException): operations.artifact_path(ids[1])
        listed=operations.list_operations()
        self.assertEqual(len(listed),2);self.assertTrue(all(v["status"]=="unavailable" for v in listed))
        self.assertNotIn("PRIVATE_SYNTHETIC_SENTENCE",json.dumps(listed))
        self.assertEqual(len(list(journal.root().glob("*.json"))),2)
        storage.task_file(self.task.id).write_bytes(original_metadata)
        self.assertEqual(operations.get_operation(ids[0])["status"],"completed")

    def test_damaged_source_metadata_never_destroys_undo_or_read_copies(self):
        result=self.edit();metadata=storage.task_file(self.task.id);original=metadata.read_bytes()
        receipt=journal.path_for(result["id"]).read_bytes();metadata.write_text("{broken",encoding="utf-8")
        with self.assertRaises(HTTPException) as error:operations.get_operation(result["id"])
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(journal.path_for(result["id"]).read_bytes(),receipt)
        metadata.write_bytes(original)
        self.assertEqual(operations.undo(uuid4().hex,result["id"])["status"],"completed")

    def test_interrupted_undo_child_creation_restores_the_visible_undo_action(self):
        completed=self.edit();undo_id=uuid4().hex;original_save=journal.save
        def fail_child(value):
            if value["id"]==undo_id:raise HTTPException(503,"synthetic disk failure")
            return original_save(value)
        with patch.object(journal,"save",side_effect=fail_child):
            with self.assertRaises(HTTPException):operations.undo(undo_id,completed["id"])
        self.assertEqual(journal.load(completed["id"])["undone_by"],undo_id)
        recovered=operations.get_operation(completed["id"])
        self.assertNotIn("undone_by",recovered)
        self.assertEqual(operations.undo(uuid4().hex,completed["id"])["status"],"completed")
        self.assertEqual(self.current()["text"],self.text)

    def test_orphan_atomic_copies_are_removed_under_lock_without_touching_unknown_files(self):
        operation_id=uuid4().hex; directory=journal.root()
        temporary=directory/("."+operation_id+".json."+uuid4().hex+".tmp")
        temporary.write_text("PRIVATE_SYNTHETIC_SNAPSHOT",encoding="utf-8")
        exported=directory/("."+operation_id+".pdf."+uuid4().hex+".tmp")
        exported.write_bytes(b"PRIVATE_SYNTHETIC_EXPORT")
        unknown=directory/"user-backup.tmp";unknown.write_bytes(b"Preserve this unknown file")
        storage.delete_task(self.task.id)
        self.assertFalse(temporary.exists());self.assertFalse(exported.exists())
        self.assertEqual(unknown.read_bytes(),b"Preserve this unknown file")

    def test_deleting_task_also_removes_assistant_copies_of_its_material_registration(self):
        registered=library.register_task_material(storage.get_task(self.task.id))
        edition=notes.get_edition("material",registered["material_id"])
        self.source={"kind":"material","id":registered["material_id"],"revision":edition["revision"]}
        request=self.request("read_note",{});operations.prepare(request);operations.execute(request.operation_id)
        storage.delete_task(self.task.id)
        self.assertIsNone(journal.load(request.operation_id))
