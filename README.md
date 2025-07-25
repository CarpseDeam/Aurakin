# Aurakin - Your AI-Powered Partner for Python Development

**Build, Test, and Refine Python Applications with Your AI Co-Pilot.**

Aurakin is a revolutionary development environment that integrates a team of specialized AI agents directly into your workflow. Go from a simple idea to a fully scaffolded, runnable Python application in minutes. Then, continue to collaborate with the AI to add features, fix bugs, and generate tests, all from a single, intuitive interface.


---

## ✨ Key Features

-   🤖 **AI-Driven Scaffolding**: Describe your application in plain English, and watch as an AI Architect and Coder work together to plan and build the entire file structure and source code from scratch.
-   ✍️ **Iterative Development**: Load an existing project and ask the AI to add new features, refactor code, or fix bugs. The AI understands your project's context and makes surgical changes.
-   🖥️ **Live IDE Experience**: A multi tab code viewer with syntax highlighting, LSP powered diagnostics (error checking), and a project file tree provides a familiar and powerful editing environment.
-   🚀 **Universal Command Executor**: Right click to run commands directly within your project's isolated environment.
    -   `pip install -r requirements.txt` to set up dependencies.
    -   `pytest` to run your test suite.
    -   `python main.py` to run your application.
-   🧠 **Project-Aware Knowledge Base (RAG)**: Aurakin can "learn" your project's codebase to provide more contextually-aware responses and code modifications. You can also supplement its knowledge with external documentation.
-   🌐 **Configurable AI Models**: You have full control. Assign different powerful LLMs (like GPT,Deepseek, Gemini, Claude, or local Ollama models) to different roles (Architect, Coder, Chat) to fine-tune your AI team's performance.
-   📊 **Real-Time Project Visualizer**: See a live, animated node graph of your project's structure as the AI builds or modifies it, giving you unprecedented insight into the generation process.
-   🔌 **Extensible Plugin System**: Enhance Aurakin's capabilities by building or installing custom plugins.

---

## 🚀 Getting Started

Follow these steps to get Aurakin up and running on your local machine.

### Prerequisites

-   **Python 3.9+**
-   **Git**
-   An environment that can create Python virtual environments (e.g., `venv`).

### Installation & Setup

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/CarpseDeam/AvA_Pylon.git
    cd AvA_Pylon
    ```

2.  **Create and Activate a Virtual Environment:**
    *   **Windows:**
        ```powershell
        python -m venv .venv
        .\.venv\Scripts\Activate.ps1
        ```
    *   **macOS / Linux:**
        ```bash
        python3 -m venv .venv
        source .venv/bin/activate
        ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure API Keys:**
    *   Find the file named `.env.example` in the root directory.
    *   Make a copy of it and name it `.env`.
    *   Open the new `.env` file and fill in the API keys for the LLM services you want to use.
    ```env
    # .env
    OPENAI_API_KEY="sk-..."
    DEEPSEEK_API_KEY="sk-..."
    GEMINI_API_KEY="..."
    ANTHROPIC_API_KEY="..."
    ```
    *   *Note: You only need to fill in the keys for the models you intend to use. Ollama models will be detected automatically if Ollama is running.*

5.  **Launch the Application:**
    ```bash
    python src/ava/main.py
    ```

---

## 📖 How to Use - Your First Session

Here’s a typical workflow to take you from idea to running application.

1.  **Launch Aurakin.** You'll be greeted with the main chat interface.

2.  **Create a New Project.**
    *   The "Build" mode should be selected by default.
    *   In the chat input, describe the application you want to build. For example:
        > `A simple command-line calculator that can add, subtract, multiply, and divide two numbers.`
    *   Click **Build**.

3.  **Watch the Magic Happen!**
    *   The **Project Visualizer** and **Code Viewer** windows will appear.
    *   You'll see the AI Architect plan the file structure in the visualizer.
    *   Then, you'll see the AI Coder write the code for each file, streaming it live into the Code Viewer tabs.

4.  **Run Your New Application!**
    *   Once the AI is finished, your project is ready to go. Now, use the **Universal Command Executor**:
    *   In the Code Viewer's file tree, find `requirements.txt`.
    *   **Right-click** it and select **"Install Dependencies"**. Watch the live output in the "Executor Log" panel at the bottom.
    *   Once installed, find `main.py`.
    *   **Right-click** it and select **"Run Project"**. The log panel will now show the output of your running application!

5.  **Modify and Refine.**
    *   Go back to the main chat window.
    *   Type a request to modify the project, for example:
        > `Add a feature to calculate exponents.`
    *   Click **Build** again. The AI will analyze the existing code and make the necessary changes to add the new feature.

You have now successfully created and modified a project using your AI co-pilot! Explore, experiment, and see what you can build.