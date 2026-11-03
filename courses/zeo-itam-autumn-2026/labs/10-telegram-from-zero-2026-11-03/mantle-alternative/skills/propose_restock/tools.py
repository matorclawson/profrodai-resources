from rasa.mantle.tools.decorator import ToolContext, tool
from rasa.mantle.tools.result import ToolResult

import shop


def sender_of(context):
    """Who is asking, as the channel reports it. The person cannot type this field.

    One place to read it, so the class can check it once.
    """
    return getattr(context, "sender_id", None)


@tool(description="Propose how many tubs to restock for one flavor. Only the owner may ask. Changes nothing on the shelf.")
async def propose_restock(context: ToolContext, flavor: str) -> ToolResult:
    return ToolResult(llm_response={"reply": shop.restock_reply(sender_of(context), flavor)})
