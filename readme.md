# AI Autobiography

**AI Autobiographer** is a framework that uses AI agents to conduct interviews and write biographies for users 📝

**Key Features**:

- 🤝 Natural conversation flow
- 🧠 Intelligent memory management
- 📚 Structured biography creation
- 🔄 Continuous learning from interactions
- 🔌 Optional backend service mode

**Documentation**:

- [Design](docs/design.md)
- [InterviewSession](docs/interview_session.md)

## Setup

### Environment Variables

Create a `.env` file in the root directory. Copy the `.env.example` file and fill in the values.

### Python Dependencies

Recommend Python version: 3.12

Install Python dependencies by running:

```bash
pip install -r requirements.txt
```

### PyAudio (optional, for voice features)

To use voice input, you need to install PyAudio. For macOS, you can install PortAudio using Homebrew. Here's how to fix it:

First, install PortAudio using Homebrew:

```bash
brew install portaudio
```

Then, install PyAudio with pip, but we need to specify the path to PortAudio:

```bash
pip install --global-option='build_ext' --global-option='-I/opt/homebrew/include' --global-option='-L/opt/homebrew/lib' pyaudio
```

### Database (optional, for server mode)

Run the database setup script to create the database and tables:

```bash
# Create database and tables (preserves existing data)
python src/main.py --mode setup_db

# Reset database (WARNING: deletes all existing data)
python src/main.py --mode setup_db --reset
```

Note: This will create the database and tables, but **terminal mode doesn't use the database**.

## Usage

### Terminal Mode

Run the interviewer in terminal mode with:

```bash
python src/main.py --mode terminal --user_id <USER_ID>
```

Optional Parameters:

- `--user_agent`: Enable user agent mode
- `--voice_output`: Enable voice output
- `--voice_input`: Enable voice input
- `--restart`: Clear previous session data and restart

Reminder:

- If you use user agent mode, you need to specify the user ID, which is the name of the user profile in the `USER_AGENT_PROFILES_DIR` directory in the `.env` file.

Examples:

```bash
# Basic run with just user ID
python src/main.py --user_id john_doe

# Run with voice features enabled
python src/main.py --user_id john_doe --voice_input --voice_output

# Restart a session with user agent
python src/main.py --user_id john_doe --restart --user_agent
```

### Server Mode

Run the interviewer in server mode with:

```bash
python src/main.py --mode server --port 8000
```

### Commands for Evaluations

For offline evaluations, you can run the evaluation scripts directly.

```bash
# Evaluate biography completeness
python evaluations/biography_completeness.py --user_id ellie

# Evaluate biography groundedness
python evaluations/biography_groundedness.py --user_id ellie
```

For online evaluations, set the `EVAL_MODE` environment variable to `true` in the `.env` file. Please check `.env.example` for more details.

Reminder: it will make the program slower.

```text
EVAL_MODE="true"
```

### Commands for Testing

```bash
pytest tests/[folder_name]/[test_file_name].py
```
