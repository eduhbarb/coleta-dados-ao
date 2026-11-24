# coleta-dados-ao

Aplicativo desktop leve e autocontido em Python para coleta de disciplinas, turmas, docentes, locais e horários do **Aluno Online da UERJ**, com exportação local em **JSON / CSV** e envio autenticado para o **Firebase Firestore**.

## Recursos

- **Interface desktop leve (`pywebview` + WebView2 do Windows)** — sem navegador pesado embutido.
- **Autenticação direta no Aluno Online em memória** — matrícula e senha nunca são salvas em disco, logs ou banco de dados.
- **Escopo configurável** — colete todas as disciplinas do currículo, apenas **Obrigatórias** ou apenas **Definidas** (com mesclagem automática ao atualizar um período existente no Firestore).
- **Log em tempo real e tabela de visualização** — acompanhe cada disciplina consultada (sequencial, pausa de 300 ms, decodificação `windows-1252`) e filtre os resultados.
- **Exportação local offline** — salve e abra arquivos `.json` e exporte `.csv` mesmo sem conexão com o Firebase.
- **Envio para o Firebase Spark** — login com Google no navegador padrão e gravação via Firestore REST API respeitando as regras de segurança do seu projeto.

## Privacidade e segurança

- Nenhuma credencial ou configuração privada de projeto Firebase vem embutida no código-fonte.
- O campo `alreadyTaken` (se o aluno já cursou a matéria) é descartado durante a leitura.
- Matrícula, nome do aluno e senha nunca são gravados nos arquivos exportados nem no Firestore.

## Configuração do Firebase (opcional)

Você pode configurar `projectId`, `apiKey` e `authDomain` diretamente pela interface no botão **Configurar Firebase** (salvo localmente em `%APPDATA%\coleta-dados-ao\config.json`), ou criar um arquivo `config.json` ao lado do executável baseado em `config.example.json`.

## Desenvolvimento e testes

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m unittest discover -s tests -v
python src/main.py
```

## Gerar executável (`.exe`)

```powershell
.\build.ps1
```

O executável autocontido será gerado em `dist\coleta-dados-ao.exe`.

## Licença

MIT — veja [LICENSE](LICENSE).
