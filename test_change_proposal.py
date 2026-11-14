from schemas import ChangeProposalList, extract_json_dict
from tools.change_proposal import _format_proposal


def test_change_proposal_schema():

    proposal = ChangeProposalList.model_validate({

        "summary": "增强 run_tool 错误日志",

        "proposals": [

            {
                "file": "tools/tool_manager.py",
                "change_type": "modify",
                "description": "在参数校验失败时记录 warning",
                "risk": "low",
                "preview": "log_tool_call 前增加 logger.warning",
            }

        ],

    })


    text = _format_proposal(proposal)


    assert "修改方案" in text

    assert "tool_manager.py" in text

    assert "尚未执行任何文件改动" in text



def test_extract_json_dict_from_mixed_text():

    mixed = (
        "说明如下\n"
        '{"summary":"test","proposals":[]}'
    )


    data = extract_json_dict(mixed)


    assert data is not None

    assert data["summary"] == "test"



if __name__ == "__main__":

    test_change_proposal_schema()

    test_extract_json_dict_from_mixed_text()

    print("change proposal schema tests passed")
