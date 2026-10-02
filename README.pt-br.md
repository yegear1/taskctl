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
- **📡 Telemetria Não-Bloqueante:** Despachante de webhooks em segundo plano com timeouts e isolamento fail-safe, garantindo que falhas de rede nunca abortem commits ou o fluxo do desenvolvedor.
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
| `taskctl plan "<prompt>"` | Solicita ao agente Planner a decomposição de tarefas no `.agent/TASK.md`. |
| `taskctl next [--weight]` | Promove a próxima tarefa do backlog para `RUNNING` e notifica o agente. |
| `taskctl audit` | Executa o Auditor de Escopo nos diffs e higiene do repositório. |
| `taskctl done [mensagem]` | Valida DoD, gera commit da feature + commit de log, e envia webhook. |
| `taskctl sync` | Sincroniza o status ativo do `.agent/TASK.md` com a nota do Maestri. |
| `taskctl quota` | Inspeciona em tempo real as cotas dos perfis Multigravity. |
| `taskctl ws [nome]` | Cria e conecta um workspace completo no Maestri para o repositório. |
| `taskctl notify <msg>` | Envia um evento sob demanda via webhook configurado. |

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

---

## 📄 Licença

MIT © [yegear](https://github.com/yegear)
