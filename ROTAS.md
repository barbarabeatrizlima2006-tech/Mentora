# Rotas da API Mentora

Rotas marcadas com ** exigem o cabeçalho `Authorization: Bearer <token>`.
Erros sempre voltam como `{"erro": "mensagem"}`.

## Conta
 Método e rota -  Corpo - Resposta 

 `POST /api/usuarios` : `{nome, email, senha}` (senha: 8+ caracteres) -> 201 `{usuario, token}` :
 `POST /api/login` : `{email, senha}` -> 200 `{usuario, token}` 
 ** `GET /api/me` : dados do usuário ->
 ** `PUT /api/me` : `{nome, email, telefone, data_nascimento}` (todos opcionais) - usuário atualizado 

## Público
Método e rota - Observação 

 `GET /api/disciplinas` - lista para categorias e formulários 
 `GET /api/professores?busca=&disciplina=&limit=` - `disciplina` aceita nome ou id; só professores `ativo` 
 `GET /api/professores/<id>` - perfil completo + 5 últimas avaliações 
 `GET /api/professores/<id>/horarios?dias=14` - horários livres com data real (máx. 30 dias) 
 `GET /api/arquivos/fotos/<nome>` - foto de perfil 

## Aluno **
 Método e rota - Corpo - Observação 

 `POST /api/solicitacoes` - `{id_professor, id_disciplina, data_hora}` - `data_hora` = valor de `/horarios` (ex.: `2026-11-02T19:00:00`) 
 `GET /api/aluno/aulas` - traz `status`, `pode_confirmar`, `pode_avaliar`, `pagamento` 
 `POST /api/aulas/<id>/confirmar` - `{pin}` - 5 erros seguidos invalidam o PIN 
 `POST /api/aulas/<id>/avaliacao` - `{nota (1-5), comentario}` - só depois de confirmar; uma vez por aula 

## Professor **
 Método e rota - Corpo - Observação 

 `POST /api/professor/cadastro` - `{descricao, formacao, experiencia, modalidade, disciplinas, preco, disponibilidade}` -  cria o perfil como `pendente`. `disciplinas`: `[1,4]` + `preco` único, ou `[{id, preco}]` 
 `POST /api/professor/documentos` | multipart: `foto` (JPG/PNG, 5 MB), `comprovante` (PDF/JPG/PNG, 10 MB) | o tipo é conferido pelo conteúdo |
 `GET /api/professor/status` -- `{cadastrado, status}` 
 `GET` / `PUT /api/professor/perfil` - `{nome, descricao, formacao, experiencia, modalidade}` 
 `GET` / `PUT /api/professor/disciplinas` - `{disciplinas: [{id, preco}]}` - substitui a lista inteira 
 `GET` / `PUT /api/professor/disponibilidade` - `{disponibilidade: [{dia_semana, hora_inicio, hora_fim}]}` - substitui tudo; `Seg` ou `Segunda`; horas `HH:MM`; faixa de 1h+ |
 `GET /api/professor/pedidos` -- pendentes primeiro 
 `POST /api/professor/pedidos/<id>/aceitar` -- cria contrato + aula + pagamento `retido` (exige perfil `ativo`) 
 `POST /api/professor/pedidos/<id>/recusar` -- avisa o aluno 
 `GET /api/professor/agenda` -- aulas ainda não confirmadas 
 `POST /api/aulas/<id>/pin` -- gera PIN de 4 dígitos, válido por 120 min 
 `GET /api/professor/pagamentos` - `retido` / `liberado` 
 `GET /api/professor/painel` - aulas e ganhos do mês, nota, alunos ativos, pedidos pendentes 

## Notificações ** (aluno e professor)
 Método e rota 

 `GET /api/notificacoes?limit=` → `{nao_lidas, itens}` 
 `POST /api/notificacoes/<id>/lida` 
 `POST /api/notificacoes/lidas` (marca todas) 

## Admin ** (usuário com `tipo = 'admin'`)
 Método e rota - Corpo 

 `GET /api/admin/professores?status=pendente` 
 `PATCH /api/admin/professores/<id>` - `{status: "ativo" \| "recusado" \| "inativo" \| "pendente"}` 
 `GET /api/admin/professores/<id>/comprovante` - baixa o documento enviado 

Fluxo completo: aluno `POST /api/solicitacoes` → professor `aceitar` → professor `POST /api/aulas/<id>/pin` → aluno `confirmar` com o PIN (libera o pagamento) → aluno `avaliacao`.
