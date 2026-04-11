from livekit.agents import AgentServer, AgentSession, Agent, room_io


class InterviewAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="""
        You are a helpful voice AI assistant. Your name is Rahul
        """)

class TechnicalAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="""
        You are a technical interviewer. Ask questions to the candidate and evaluate their answers.
        """)

class HRInterviewAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="""
        You are a HR interviewer. Ask questions to the candidate and evaluate their answers.
        """)

