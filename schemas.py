import json
import re
from typing import Literal, Union

from pydantic import BaseModel, ValidationError, model_validator

import config.settings as settings


class CalculatorArgs(BaseModel):
    a: int | float
    b: int | float


class SummarizerArgs(BaseModel):
    text: str


class FileReaderArgs(BaseModel):
    path: str


class ListRepoFilesArgs(BaseModel):
    path: str = ""
    extensions: str = ""
    max_results: int = 100


class ReadRepoFileArgs(BaseModel):
    path: str
    max_chars: int = 20000


class SearchInRepoArgs(BaseModel):
    keyword: str
    path: str = ""
    extensions: str = ""
    max_results: int = 20


class AnalyzeRepoStructureArgs(BaseModel):
    path: str = ""
    max_depth: int = 3


class FindFileDependenciesArgs(BaseModel):
    path: str = ""
    symbol: str = ""
    query_mode: Literal["dependencies", "symbol", "auto"] = "auto"
    max_results: int = 100

    @model_validator(mode="after")
    def validate_query(self):
        path = str(self.path).strip()
        symbol = str(self.symbol).strip()
        mode = self.query_mode

        if mode == "auto":
            if symbol:
                mode = "symbol"
            elif path:
                mode = "dependencies"
            else:
                raise ValueError("需要提供 path 或 symbol")

        if mode == "dependencies" and not path:
            raise ValueError("dependencies 模式需要提供 path")

        if mode == "symbol" and not symbol:
            raise ValueError("symbol 模式需要提供 symbol")

        self.path = path
        self.symbol = symbol
        self.query_mode = mode
        return self


class ChangeItem(BaseModel):
    file: str
    change_type: str
    description: str
    risk: str
    preview: str


class ChangeProposalList(BaseModel):
    summary: str
    proposals: list[ChangeItem]
    affected_files: list[str] | None = None
    risk_notes: str | None = None


class ProposeCodeChangesArgs(BaseModel):
    task: str
    target_files: str = ""
    affected_files: str = ""
    max_chars: int = 20000


class GitCreateBackupArgs(BaseModel):
    message: str = "agent backup before change"


class GitStatusArgs(BaseModel):
    pass


class GitRollbackArgs(BaseModel):
    pass


class WriteRepoFileArgs(BaseModel):
    path: str
    content: str


class FileChange(BaseModel):
    path: str
    new_content: str


class _PatchToolArgsBase(BaseModel):
    changes: list[FileChange] | None = None
    path: str | None = None
    new_content: str | None = None

    @model_validator(mode="after")
    def validate_input_mode(self):
        has_legacy = (
            self.path is not None
            and str(self.path).strip() != ""
            and self.new_content is not None
        )
        has_changes = self.changes is not None and len(self.changes) > 0

        if has_legacy and has_changes:
            raise ValueError("path/new_content 与 changes 不能同时使用")

        if not has_legacy and not has_changes:
            raise ValueError("需要提供 path + new_content 或 changes")

        return self


class GenerateUnifiedDiffArgs(_PatchToolArgsBase):
    pass


class ApplyPatchArgs(_PatchToolArgsBase):
    pass


class VerifyChangeArgs(BaseModel):
    """Post-apply verification (v0.10.2)."""

    checks: str = "patched_files,syntax"
    paths: str = ""


def normalize_to_changes(
    *,
    path: str | None = None,
    new_content: str | None = None,
    changes: list[FileChange] | list[dict] | None = None,
) -> tuple[list[FileChange] | None, str | None]:
    has_legacy = (
        path is not None
        and str(path).strip() != ""
        and new_content is not None
    )
    has_changes = changes is not None and len(changes) > 0

    if has_legacy and has_changes:
        return None, "参数错误: path/new_content 与 changes 不能同时使用"

    if not has_legacy and not has_changes:
        return None, "参数错误: 需要提供 path + new_content 或 changes"

    if has_legacy:
        rel = str(path).strip().replace("\\", "/")

        if not rel:
            return None, "路径不能为空"

        return [FileChange(path=rel, new_content=new_content)], None

    parsed: list[FileChange] = []
    seen: set[str] = set()

    for item in changes or []:
        if isinstance(item, FileChange):
            change = item
        else:
            change = FileChange.model_validate(item)

        rel = str(change.path).strip().replace("\\", "/")

        if not rel:
            return None, "路径不能为空"

        if rel in seen:
            return None, "参数错误: changes 中存在重复路径: " + rel

        seen.add(rel)
        parsed.append(FileChange(path=rel, new_content=change.new_content))

    if len(parsed) > settings.PATCH_MAX_FILES:
        return (
            None,
            "参数错误: changes 文件数超过上限: "
            + str(len(parsed))
            + " > "
            + str(settings.PATCH_MAX_FILES),
        )

    return parsed, None


class ToolCall(BaseModel):
    action: str
    args: dict = {}


class FinishResponse(BaseModel):
    action: str
    answer: str


AgentAction = Union[ToolCall, FinishResponse]


def _extract_json_object(text: str):

    text = text.strip()


    code_block = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        re.DOTALL,
    )

    if code_block:

        return code_block.group(1)


    start = text.find("{")


    if start == -1:

        return None


    depth = 0

    in_string = False

    escape = False


    for index in range(start, len(text)):

        char = text[index]


        if escape:

            escape = False

            continue


        if char == "\\" and in_string:

            escape = True

            continue


        if char == '"':

            in_string = not in_string

            continue


        if in_string:

            continue


        if char == "{":

            depth += 1


        elif char == "}":

            depth -= 1


            if depth == 0:

                return text[start:index + 1]


    return None



def _parse_agent_json(text: str):

    try:

        data = json.loads(text)

    except json.JSONDecodeError:

        return None


    if not isinstance(data, dict):

        return None


    try:

        if data.get("action") == "finish":

            return FinishResponse.model_validate(data)


        return ToolCall.model_validate(data)


    except ValidationError:

        return None



def parse_agent_response(response: str) -> Union[str, ToolCall, FinishResponse]:

    candidates = []


    stripped = response.strip()


    if stripped:

        candidates.append(stripped)


    extracted = _extract_json_object(response)


    if extracted and extracted not in candidates:

        candidates.append(extracted)


    for candidate in candidates:

        parsed = _parse_agent_json(candidate)


        if parsed is not None:

            return parsed


    return response



def extract_json_dict(text: str):

    candidates = []


    stripped = text.strip()


    if stripped:

        candidates.append(stripped)


    extracted = _extract_json_object(text)


    if extracted and extracted not in candidates:

        candidates.append(extracted)


    for candidate in candidates:

        try:

            data = json.loads(candidate)

        except json.JSONDecodeError:

            continue


        if isinstance(data, dict):

            return data


    return None
