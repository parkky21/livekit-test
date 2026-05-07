from livekit.agents import ChatContext, RunContext

def get_chat_context_without_instruction(run_ctx: RunContext) -> ChatContext:
    return run_ctx.session.history.copy(
            exclude_function_call=True,
            exclude_instructions=True,
        )

def get_chat_context_with_instruction(ctx_obj: RunContext) -> ChatContext:
    return ctx_obj.session.history.copy(
            exclude_function_call=True,
            exclude_instructions=False,
        )
    