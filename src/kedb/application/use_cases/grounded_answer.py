
from kedb.application.dto import GroundedAnswer


class GenerateGroundedAnswer:
    def __init__(self, llm):
        self.llm = llm

    def execute(
        self,
        question: str,
        evidence: list[dict],
        history: list[dict] | None = None,
    ) -> GroundedAnswer:

        context = "\n\n".join(
            f"[{i}] {e['title']} v{e.get('version_number', '?')}\n{e['content']}"
            for i, e in enumerate(evidence, 1)
        )

        if not context:
            context = "No new KEDB articles were retrieved for this message."

        history = history or []
        conversation = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in history
        )

        return self.llm.structured(
            system=(
                "You are a conversational IT support assistant that helps users "
                "understand incidents using approved Known Error Database (KEDB) knowledge. "

                "GROUNDING RULES: "
                "Every new technical diagnosis, troubleshooting step, or recommended "
                "solution must be supported by relevant approved KEDB evidence. "
                "Never invent technical details, causes, specifications, or procedures. "
                "Never use general IT knowledge to fill gaps in the documentation. "

                "CONVERSATIONAL BEHAVIOR: "
                "Respond to every user message in the context of the conversation. "
                "You may answer conversational questions, ask clarifying questions, "
                "and refer to information already established in earlier messages. "
                "Do not automatically report that no solution was found merely "
                "because the latest retrieval returned no articles. "

                "CONVERSATION MEMORY: "
                "Use previous user and assistant messages to understand follow-up "
                "questions and remember previously discussed details. "
                "You may repeat or explain a previously documented solution "
                "that was already provided in the conversation. "
                "However, do not treat unsupported claims from earlier messages "
                "as verified KEDB evidence. "
                "Do not introduce new technical recommendations based solely "
                "on conversation history. "

                "KNOWN INCIDENTS: "
                "If relevant KEDB evidence contains an applicable solution, "
                "explain it accurately, preserving important technical details "
                "and limitations. "
                "Do not combine solutions from different incidents. "

                "UNKNOWN INCIDENTS: "
                "If no applicable documented solution is available in either "
                "the current evidence or previously established documented answers, "
                "state that no applicable solution was found in the supplied "
                "approved KEDB information. "
                "Do not invent troubleshooting steps or solutions. "

                "CLARIFICATION: "
                "If the user's message is vague or missing essential information, "
                "ask a specific clarifying question. "
                "Do not assume that an unrelated retrieved article applies. "
                "If the user corrects earlier details, prioritize the correction. "

                "TOPIC CHANGES: "
                "Recognize when the user introduces a different incident. "
                "Do not carry over solutions or diagnoses from previous incidents. "
                "Use earlier messages only when relevant to the current question. "

                "EVIDENCE REFERENCES: "
                "Reference only genuinely relevant KEDB articles. "
                "Never fabricate article references. "
                "If no relevant evidence supports the response, "
                "return no evidence references."
            ),
            user=(
                f"Conversation:\n{conversation}\n\n"
                f"Latest user message:\n{question}\n\n"
                f"Newly retrieved KEDB evidence:\n{context}"
            ),
            schema=GroundedAnswer,
        )
