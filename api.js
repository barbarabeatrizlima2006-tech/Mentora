// =====================================================================
// api.js  —  CAMADA DE CONEXÃO ENTRE O SITE E A API FLASK (app.py)
// Rotas conferidas com o ROTAS.md e com os controllers do backend.
// =====================================================================
const API_URL = "http://localhost:3000/api";

const ROTAS = {
  login:            "/login",                         // POST {email, senha} -> {usuario, token}
  cadastro:         "/usuarios",                      // POST {nome, email, senha} -> {usuario, token}
  meuUsuario:       "/me",                            // GET / PUT
  disciplinas:      "/disciplinas",
  professores:      "/professores",
  professor:        id => `/professores/${id}`,
  horarios:         id => `/professores/${id}/horarios`,
  solicitarAula:    "/solicitacoes",                  // POST {id_professor, id_disciplina, data_hora}
  minhasAulas:      "/aluno/aulas",
  confirmarAula:    id => `/aulas/${id}/confirmar`,   // POST {pin}
  avaliarAula:      id => `/aulas/${id}/avaliacao`,   // POST {nota, comentario}
  cadastroProf:     "/professor/cadastro",            // POST JSON
  documentosProf:   "/professor/documentos",          // POST multipart (foto, comprovante)
  statusProf:       "/professor/status",
  perfilProf:       "/professor/perfil",              // GET / PUT
  disciplinasProf:  "/professor/disciplinas",         // GET / PUT {disciplinas:[{id, preco}]}
  dispProf:         "/professor/disponibilidade",     // GET / PUT
  pedidos:          "/professor/pedidos",
  responderPedido:  (id, acao) => `/professor/pedidos/${id}/${acao}`, // POST (aceitar | recusar)
  agenda:           "/professor/agenda",
  gerarPin:         id => `/aulas/${id}/pin`,         // POST -> {pin}
  pagamentos:       "/professor/pagamentos",
  painel:           "/professor/painel",
  notificacoes:     "/notificacoes",
  lerNotificacoes:  "/notificacoes/lidas"             // POST (marca todas)
};

const Sessao = {
  token()   { return localStorage.getItem("token"); },
  usuario() { return JSON.parse(localStorage.getItem("usuario") || "null"); },
  salvar(token, usuario) {
    localStorage.setItem("token", token);
    localStorage.setItem("usuario", JSON.stringify(usuario));
  },
  logado()  { return !!localStorage.getItem("token"); },
  sair()    { localStorage.removeItem("token"); localStorage.removeItem("usuario"); }
};

async function chamarApi(caminho, metodo = "GET", corpo = null) {
  const opcoes = { method: metodo, headers: {} };
  if (Sessao.token()) opcoes.headers["Authorization"] = "Bearer " + Sessao.token();

  if (corpo instanceof FormData) {
    opcoes.body = corpo;
  } else if (corpo) {
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }

  let resposta;
  try {
    resposta = await fetch(API_URL + caminho, opcoes);
  } catch (e) {
    throw new Error("Não foi possível conectar ao servidor. O Flask está rodando?");
  }

  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) {
    if (resposta.status === 401) Sessao.sair();
    throw new Error(dados.erro || "Erro " + resposta.status);
  }
  return dados;
}

const Api = {
  // --- conta ---
  async entrar(email, senha) {
    const r = await chamarApi(ROTAS.login, "POST", { email, senha });
    Sessao.salvar(r.token, r.usuario);
    return r.usuario;
  },
  async cadastrar(nome, email, senha) {
    const r = await chamarApi(ROTAS.cadastro, "POST", { nome, email, senha });
    // o cadastro já devolve o token; o /me completa os dados (inclui "tipo")
    Sessao.salvar(r.token, r.usuario);
    try { Sessao.salvar(r.token, await chamarApi(ROTAS.meuUsuario)); } catch (e) { /* segue com o básico */ }
    return r.usuario;
  },
  meuUsuario:       ()        => chamarApi(ROTAS.meuUsuario),
  salvarMeuUsuario: dados     => chamarApi(ROTAS.meuUsuario, "PUT", dados),

  // --- público ---
  disciplinas:      ()        => chamarApi(ROTAS.disciplinas),
  professores:      ()        => chamarApi(ROTAS.professores),
  professor:        id        => chamarApi(ROTAS.professor(id)),
  horarios:         id        => chamarApi(ROTAS.horarios(id)),

  // --- aluno ---
  solicitarAula:    dados     => chamarApi(ROTAS.solicitarAula, "POST", dados),
  minhasAulas:      ()        => chamarApi(ROTAS.minhasAulas),
  confirmarAula:    (id, pin) => chamarApi(ROTAS.confirmarAula(id), "POST", { pin }),
  avaliarAula:      (id, nota, comentario) => chamarApi(ROTAS.avaliarAula(id), "POST", { nota, comentario }),

  // --- professor ---
  cadastrarProfessor: dados   => chamarApi(ROTAS.cadastroProf, "POST", dados),
  enviarDocumentos:   form    => chamarApi(ROTAS.documentosProf, "POST", form),
  statusProf:       ()        => chamarApi(ROTAS.statusProf),
  perfilProf:       ()        => chamarApi(ROTAS.perfilProf),
  salvarPerfilProf: dados     => chamarApi(ROTAS.perfilProf, "PUT", dados),
  disciplinasProf:  ()        => chamarApi(ROTAS.disciplinasProf),
  salvarDisciplinasProf: lista => chamarApi(ROTAS.disciplinasProf, "PUT", { disciplinas: lista }),
  disponibilidadeProf: ()     => chamarApi(ROTAS.dispProf),
  pedidos:          ()        => chamarApi(ROTAS.pedidos),
  responderPedido:  (id, acao) => chamarApi(ROTAS.responderPedido(id, acao), "POST"),
  agenda:           ()        => chamarApi(ROTAS.agenda),
  gerarPin:         id        => chamarApi(ROTAS.gerarPin(id), "POST"),
  pagamentos:       ()        => chamarApi(ROTAS.pagamentos),
  painel:           ()        => chamarApi(ROTAS.painel),

  // --- notificações ---
  notificacoes:     ()        => chamarApi(ROTAS.notificacoes),
  lerNotificacoes:  ()        => chamarApi(ROTAS.lerNotificacoes, "POST")
};