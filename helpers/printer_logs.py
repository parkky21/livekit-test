from livekit.agents import RunContext

def print_conversation_context(context: RunContext):
    chat = context.session._chat_ctx.copy(
        exclude_function_call=True,
        exclude_instructions=False,
    )
    print("--- Current Conversation Context ---")
    # In some versions of livekit-agents, messages is a method. In others, a property.
    messages_list = chat.messages() if callable(chat.messages) else chat.messages
    for msg in messages_list:
        content = getattr(msg, "text_content", str(msg.content))
        print(f"[{msg.role}]: {content}")
    print("------------------------------------")