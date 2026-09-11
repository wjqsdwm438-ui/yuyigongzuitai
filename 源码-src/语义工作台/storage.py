"""仅用标准库保存不可覆盖的记录与证据；不授予业务执行权限。"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"重复字段：{key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"不允许非标准数字：{value}")
    result = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                        parse_constant=constant)
    encode(result).encode("utf-8")
    return result


class Store:
    def __init__(self, root, project=None, readonly=False):
        self.root = Path(root).resolve()
        self.project = str(Path(project).resolve()).casefold() if project is not None else None
        if project is not None and not Path(project).is_dir():
            raise ValueError("项目根目录不存在")
        path = self.root / "workbench.sqlite3"
        if readonly:
            self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)
            self.db.execute("PRAGMA query_only=ON")
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, timeout=15)
        try:
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            owner = self.db.execute("SELECT project FROM project_scope WHERE id=1").fetchone() if "project_scope" in tables else None
            if owner:
                if self.project is not None and owner[0] != self.project:
                    raise ValueError("项目隔离：数据目录已属于其他项目，拒绝读取或写入")
                self.project = owner[0]
            elif self.project is not None:
                has_data = any(self.db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                               for table in ("records", "evidence") if table in tables)
                if has_data or readonly:
                    raise ValueError("未归属的历史记录不可自动绑定项目；请使用独立项目库，历史数据仅显式回查")
                self.db.execute("CREATE TABLE IF NOT EXISTS project_scope(id INTEGER PRIMARY KEY CHECK(id=1), project TEXT NOT NULL)")
                self.db.execute("INSERT INTO project_scope VALUES(1,?)", (self.project,))
                self.db.commit()
        except BaseException:
            self.db.close()
            raise
        if readonly:
            return
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS records(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence(
          id TEXT PRIMARY KEY, source TEXT NOT NULL, digest TEXT NOT NULL,
          created TEXT NOT NULL, content BLOB NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS unique_rule_version ON records(
          json_extract(payload, '$.规则编号'), json_extract(payload, '$.版本'))
          WHERE kind='规则版本';
        CREATE TRIGGER IF NOT EXISTS immutable_records_update BEFORE UPDATE ON records
          BEGIN SELECT RAISE(ABORT, '历史记录禁止覆盖'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_records_delete BEFORE DELETE ON records
          BEGIN SELECT RAISE(ABORT, '历史记录禁止删除'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_evidence_update BEFORE UPDATE ON evidence
          BEGIN SELECT RAISE(ABORT, '历史证据禁止覆盖'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_evidence_delete BEFORE DELETE ON evidence
          BEGIN SELECT RAISE(ABORT, '历史证据禁止删除'); END;
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def atomic(self):
        """多个关联记录一次提交；嵌套调用不提前提交父事务。"""
        owner = not self.db.in_transaction
        if owner:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            if owner:
                self.db.commit()
        except BaseException:
            if owner:
                self.db.rollback()
            raise

    def capture(self, path):
        path = Path(path).resolve(strict=True)
        content = path.read_bytes()
        content.decode("utf-8", errors="strict")
        ident = "证据-" + uuid.uuid4().hex
        with self.atomic():
            self.db.execute("INSERT INTO evidence VALUES(?,?,?,?,?)", (
                ident, str(path), hashlib.sha256(content).hexdigest(),
                datetime.now(timezone.utc).isoformat(), content))
        return ident

    def evidence(self, ident, current=False):
        row = self.db.execute("SELECT source,digest,created,content FROM evidence WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("证据不存在：" + ident)
        source, digest, created, content = row
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("历史证据完整性检查失败")
        result = {"编号": ident, "来源": source, "摘要": digest, "记录时间": created,
                  "历史内容": content.decode("utf-8", errors="strict")}
        if current:
            try:
                result["当前来源一致"] = hashlib.sha256(Path(source).read_bytes()).hexdigest() == digest
            except OSError:
                result["当前来源一致"] = False
        return result

    def get(self, ident):
        row = self.db.execute("SELECT kind,created,payload FROM records WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("记录不存在：" + ident)
        return {"编号": ident, "类型": row[0], "记录时间": row[1], "内容": json.loads(row[2])}

    def require_ref(self, ident, kind=None):
        if not isinstance(ident, str):
            raise ValueError("引用必须是编号文本")
        record = self.get(ident)
        if kind and record["类型"] != kind:
            raise ValueError(f"引用类型应为{kind}：{ident}")
        return record

    def add(self, kind, payload):
        required = {
            "项目": ["名称", "路径"],
            "规则版本": ["规则编号", "版本", "正文", "来源证据", "语义"],
            "案例": ["标题", "预期", "实际", "来源证据"],
            "决定": ["案例", "处置", "依据", "输入证据", "规则版本"],
            "复用审阅": ["新案例", "旧案例", "结论", "依据", "关键差异"],
            "验证": ["对象", "预期", "观察", "结论", "证据"],
            "处理任务": ["案例", "问题", "上下文"],
            "专项任务": ["问题", "选择依据", "能力序列", "来源证据"],
            "专项产物": ["任务", "能力", "产物", "来源证据", "审阅边界", "摘要"],
        }
        if kind not in required or not isinstance(payload, dict):
            raise ValueError("不支持的记录类型或非对象内容")
        for key in required[kind]:
            if key not in payload or payload[key] is None or payload[key] == "":
                raise ValueError("缺少必填字段：" + key)
        structured = {"来源证据", "输入证据", "规则版本", "证据", "语义", "上下文", "能力序列", "产物"}
        for key in required[kind]:
            if key not in structured and (not isinstance(payload[key], str) or not payload[key].strip()):
                raise ValueError(key + "必须是非空文本")
        if kind == "项目":
            path = Path(payload["路径"])
            if not path.is_absolute() or not path.is_dir():
                raise ValueError("项目路径必须是存在的绝对目录")
            if self.project is not None and str(path.resolve()).casefold() != self.project:
                raise ValueError("项目记录与当前数据库所属项目不同")
        if kind == "处理任务":
            self.require_ref(payload["案例"], "案例")
            if not isinstance(payload["上下文"], dict):
                raise ValueError("上下文必须是对象")
        if kind == "专项任务":
            from .dispatch import CAPABILITIES
            if not isinstance(payload["能力序列"], list) or not payload["能力序列"] or any(c not in CAPABILITIES or not CAPABILITIES[c]["产物"] for c in payload["能力序列"]):
                raise ValueError("专项任务能力序列无效")
        if kind == "专项产物":
            self.require_ref(payload["任务"], "专项任务")
            if not isinstance(payload["产物"], dict):
                raise ValueError("专项产物必须是对象")
        for field in ("来源证据", "输入证据", "证据"):
            if field in payload:
                if not isinstance(payload[field], list) or not payload[field]:
                    raise ValueError(field + "必须是非空证据编号列表")
                for ident in payload[field]:
                    self.evidence(ident)
        if kind == "规则版本":
            semantic = payload["语义"]
            keys = ("主体", "动作", "对象", "情态", "条件", "范围", "例外")
            if not isinstance(semantic, dict) or any(k not in semantic for k in keys):
                raise ValueError("规则语义必须保留主体、动作、对象、情态、条件、范围、例外")
            for key in ("主体", "动作", "对象", "情态", "范围"):
                if not isinstance(semantic[key], str) or not semantic[key].strip():
                    raise ValueError("语义字段必须是非空文本：" + key)
            if not isinstance(semantic["条件"], dict) or not isinstance(semantic["例外"], list):
                raise ValueError("条件必须为结构对象，例外必须为列表")
            # 结构完整不证明自然语言等价；条件内容由语义审阅判断。
            if any(r["内容"]["规则编号"] == payload["规则编号"] and
                   r["内容"]["版本"] == payload["版本"] for r in self.list("规则版本")):
                raise ValueError("规则版本已存在，不得覆盖")
        if kind == "决定":
            self.require_ref(payload["案例"], "案例")
            allowed = {"复用处置", "修加载或执行", "修工具或流程", "规则裁决或改稿", "新增要求", "补充证据"}
            if payload["处置"] not in allowed:
                raise ValueError("未知处置分类")
            if not isinstance(payload["规则版本"], list):
                raise ValueError("规则版本必须为列表")
            if not payload["规则版本"] and not payload.get("无规则依据说明"):
                raise ValueError("未引用规则时必须说明依据缺口")
            for ident in payload["规则版本"]:
                self.require_ref(ident, "规则版本")
        if kind == "复用审阅":
            self.require_ref(payload["新案例"], "案例")
            self.require_ref(payload["旧案例"], "案例")
            if payload["新案例"] == payload["旧案例"]:
                raise ValueError("不能将案例与自身归并")
            if payload["结论"] not in {"可复用", "需调整", "不可复用", "证据不足"}:
                raise ValueError("未知复用结论")
        if kind == "验证":
            self.require_ref(payload["对象"])
            if payload["结论"] not in {"通过", "失败", "未运行"}:
                raise ValueError("未知验证结论")
        if "替代记录" in payload:
            self.require_ref(payload["替代记录"], kind)
        payload = dict(payload, 状态="待审", 执行授权=False)
        if self.project is not None:
            payload["所属项目"] = self.project
        ident = kind + "-" + uuid.uuid4().hex
        try:
            with self.atomic():
                self.db.execute("INSERT INTO records VALUES(?,?,?,?)", (
                    ident, kind, datetime.now(timezone.utc).isoformat(), encode(payload)))
        except sqlite3.IntegrityError as error:
            raise ValueError("记录冲突，未写入：" + str(error)) from error
        return ident

    def list(self, kind=None):
        rows = self.db.execute("SELECT id FROM records WHERE kind=? ORDER BY rowid", (kind,)) if kind else self.db.execute("SELECT id FROM records ORDER BY rowid")
        return [self.get(row[0]) for row in rows.fetchall()]

    def report(self, ident):
        record = self.get(ident)
        payload = record["内容"]
        bundle = {"记录": record, "引用规则": [], "历史证据": [],
                  "边界": "记录的是提交的证据与声明；不是业务批准，不证明语义正确或实际执行。"}
        evidence = set(payload.get("来源证据", []) + payload.get("输入证据", []) + payload.get("证据", []))
        for ref in payload.get("规则版本", []):
            rule = self.require_ref(ref, "规则版本")
            bundle["引用规则"].append(rule)
            evidence.update(rule["内容"]["来源证据"])
        bundle["历史证据"] = [self.evidence(e) for e in sorted(evidence)]
        return bundle

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination.exists():
            raise ValueError("备份目标已存在，拒绝覆盖")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # 排他创建，避免存在性检查后其他进程生成同名文件而被覆盖。
        with destination.open("xb"):
            pass
        target = sqlite3.connect(destination)
        try:
            self.db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("备份完整性检查失败")
        finally:
            target.close()
        return {"备份": str(destination), "范围": "本地记录及内嵌证据，不包含外部图服务"}
