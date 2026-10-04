# taskctl

🌐 **[English](README.md) | Português**

**taskctl** é a CLI de Ciclo de Vida de Tarefas, Motor de Contratos e Orquestração Multi-Agente para **Desenvolvimento Orientado a Agentes (ADD - Agent-Driven Development)**.

Ele estabelece uma ponte determinística entre agentes de IA (Antigravity, Claude Code, Cursor, Windsurf, Maestri, Roo Code) e repositórios de código, impondo contratos estruturados de tarefas (`.agent/TASK.md`), Definições de Pronto (DoD) falseáveis, telemetria de webhooks não-bloqueante e integrações de orquestração.

---

## ⚡ Capacidades Principais

- **📋 Orquestração do Ciclo de Vida:** Comandos determinísticos para planejar, iniciar, auditar e concluir tarefas com commit duplo atômico (commit da feature + atualização da governança).
- **🛡️ Auditor de Escopo (`taskctl audit`):** Gatekeeper semântico retornando códigos de saída para CI e pre-commit hooks:
  - `0`: **APROVADO** — Pronto para conclusão.
  - `1`: **MUDANÇAS REQUERIDAS** — Correções acionáveis necessárias.
  - `2`: **REJEITADO** — Violação crítica de política; escala para o planejador/humano.
- **✅ Conventional Commits (`taskctl lint-commit`):** Política hermética de mensagem de commit para hooks `commit-msg` e CI, sem linter externo.
- **📡 Telemetria Não-Bloqueante:** Webhook e sink Vector em segundo plano. Queda de rede, endpoint inválido ou timeout nunca abortam commit nem atualização de status.
- **📈 Grafo e Tracing:** `taskctl graph` (ASCII, Mermaid, JSON, ciclos) e `taskctl trace` (spans e alertas de SLA).
- **🔌 Adaptadores de Provedores Plugáveis:** Suporte nativo a ecossistemas externos como o Maestri (criação de workspaces, notas) e [`multigravity-cli`](https://github.com/yegear1/multigravity-cli) para roteamento de perfis e cotas.
- **🌐 Arquitetura Aberta e Desacoplada:** O `taskctl` foca exclusivamente na governança e nos contratos de tarefas. O monitoramento aprofundado de cotas, perfis e isolamento de worktrees é delegado a ferramentas especializadas como o `multigravity-cli`, sem criar acoplamento forçado.
- **🌿 Conformidade Greenfield e Brownfield:** 100% aderente ao template `ye-sandbox/template-agent` e especificação de AST Markdown.

---

## 🚀 Início Rápido

### Instalação

Instale em modo editável para desenvolvimento local:

```bash
git clone https://github.com/yegear1/taskctl.git
cd taskctl
pip install -e .
```

Verifique a instalação:

```bash
taskctl --help
```

---

## 💻 Referência de Comandos

| Comando | Descrição |
| :--- | :--- |
| `taskctl init` | Inicializa `.agent/TASK.md` e `AGENTS.md` no repositório atual. |
| `taskctl status` | Exibe tarefa ativa, critérios de aceitação, status git e roteamento de cota. |
| `taskctl backlog` | Lista os itens do backlog. |
| `taskctl plan "<prompt>"` | Solicita ao Planner a decomposição de tarefas no `.agent/TASK.md`. |
| `taskctl next [light\|medium\|heavy] [--agent <nome>] [--no-handoff]` | Promove a próxima tarefa para `RUNNING` e faz o hand-off ao builder. |
| `taskctl audit [--delegate] [--agent <nome>]` | Auditor de Escopo nos diffs e na higiene do git. Saída `0` / `1` / `2`. |
| `taskctl lint-commit [msg] [--file <path>] [--rev <rev>] [--range <range>]` | Valida a mensagem contra Conventional Commits. Alias: `commit-lint`. |
| `taskctl done [mensagem] [-p] [--agent <nome>] [--no-handoff]` | Valida o DoD, gera o commit da feature e o de governança, e envia o webhook. |
| `taskctl graph [--mermaid\|--json\|--check-cycles] [--file <path>]` | Renderiza o DAG de dependências. Saída `1` se houver ciclo. |
| `taskctl dashboard [--snapshot] [--split] [--dag]` | Painel da tarefa ativa, DoD e auditoria. Alias: `tui`. |
| `taskctl trace [--last] [--id <trace_id>] [--analytics] [--json]` | Exibe spans, cascata e métricas de SLA. |
| `taskctl daemon [--watch <path>] [--once] [--json]` | Observa repositórios e publica eventos de ciclo de vida. |
| `taskctl broadcast [msg] [--watch <path>] [--json]` | Envia um resumo cross-repo ao Vector, ao canvas e ao webhook. |
| `taskctl sync [--pull]` | Envia ou puxa a nota da tarefa ativa no canvas Maestri. |
| `taskctl quota` | Inspeciona cotas dos perfis Multigravity e a recomendação de balanceamento. |
| `taskctl ws [nome] [--preset <nome>] [--workers <n>]` | Provisiona um workspace Maestri. Presets: `trinity`, `swarm`, `audit`. |
| `taskctl notify <msg>` | Envia um evento sob demanda pelo webhook configurado. |

---

## 🧪 Testes e Validação

Execute a suíte de testes e a verificação estrita de sintaxe:

```bash
# Verificação de sintaxe
python3 -m py_compile $(find taskctl -name "*.py")

# Suíte hermética de testes
python3 -m unittest discover tests

# Verificação de higiene do git
git diff --check
```

O GitHub Actions (`.github/workflows/ci.yml`) executa as mesmas verificações em Python 3.10–3.13, mais `taskctl audit` e `taskctl lint-commit`.

---

## 📄 Licença

MIT © [yegear](https://github.com/yegear)
