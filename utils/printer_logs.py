from livekit.agents import RunContext

def print_conversation_context(context: RunContext):
    chat = context.session.history.copy(
        exclude_function_call=True,
        exclude_instructions=False,
    )
    print("--- Current Conversation Context ---")
    
    # Iterate over all items to catch 'agent_config_update' which holds instructions in newer versions
    items_list = chat.items if hasattr(chat, "items") else (chat.messages() if callable(getattr(chat, "messages", None)) else getattr(chat, "messages", []))
    
    for item in items_list:
        item_type = getattr(item, "type", "message")
        
        if item_type == "message":
            content = getattr(item, "text_content", str(getattr(item, "content", "")))
            role = getattr(item, "role", "unknown")
            print(f"[{role}]: {content}")
        elif item_type == "agent_config_update":
            instructions = getattr(item, "instructions", None)
            if instructions:
                print(f"[system]: {instructions}")
    print("------------------------------------")