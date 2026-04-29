def print_conversation_context(chat):
    print("--- Current Conversation Context ---")
    # In some versions of livekit-agents, messages is a method. In others, a property.
    messages_list = chat.messages() if callable(chat.messages) else chat.messages
    for msg in messages_list:
        content = getattr(msg, "text_content", str(msg.content))
        print(f"[{msg.role}]: {content}")
    print("------------------------------------")