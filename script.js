// =====================================================================
// script.js  —  LÓGICA DAS PÁGINAS (agora alimentada pela API, não mais por dados.js)
// =====================================================================
// Padrão usado em quase todas as funções:
//   1) chama a API (await Api.algo())     2) "traduz" a resposta       3) desenha o HTML
// Funções "async" usam await para esperar o servidor responder sem travar a página.
// =====================================================================

// ---------- Utilitários ----------

// Protege contra XSS: transforma < > & " em texto inofensivo antes de colocar dado do banco no HTML
function esc(t) {
  return String(t ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Mostra erros da API para o usuário (a mensagem vem do {"erro": "..."} do Flask)
function mostrarErro(e) { alert(e.message || "Algo deu errado."); }

// Páginas privadas chamam isto no início: sem login, volta para a tela de login
function exigirLogin() {
  if (!Sessao.logado()) { window.location.href = "login.html"; return false; }
  return true;
}

function sair() { Sessao.sair(); window.location.href = "index.html"; }

// Formata data do banco ("2026-10-26T18:30:00") para "26/10 · 18:30"
function formatarData(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) + " · " +
         d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

// O banco guarda dia da semana por extenso ("Segunda"). Esta tabela converte para o número do JavaScript.
const DIAS = { "Domingo": 0, "Segunda": 1, "Terça": 2, "Quarta": 3, "Quinta": 4, "Sexta": 5, "Sábado": 6 };

// Descobre a PRÓXIMA data em que cai um dia da semana + hora (ex.: "Segunda" "18:00" -> 2026-11-02 18:00)
// É isso que o banco precisa em solicitacao_aula.data_hora_solicitada
function proximaData(diaSemana, hora) {
  const d = new Date();
  const [h, m] = hora.split(":");
  d.setHours(Number(h), Number(m), 0, 0);
  let falta = (DIAS[diaSemana] - d.getDay() + 7) % 7;
  if (falta === 0 && d < new Date()) falta = 7;   // hoje, mas o horário já passou -> semana que vem
  d.setDate(d.getDate() + falta);
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:00`;
}

// ---------- Usuário logado (vem da sessão salva no login) ----------
function usuario() {
  return Sessao.usuario() || { nome: "Visitante", email: "" };
}

// ---------- Menu do topo (escrito uma vez e usado em todas as páginas) ----------
function montarMenu(logado) {
  logado = logado && Sessao.logado();            // só mostra "Meu perfil" se existe sessão de verdade
  const direita = logado
    ? `<a href="buscar.html"><span class="avatar">${esc(usuario().nome[0])}</span> Meu perfil</a>`
    : `<a href="login.html">Entrar</a><a href="cadastro.html" class="btn">Cadastre-se</a>`;
  document.getElementById("menu").innerHTML = `
    <header class="topo">
      <a href="index.html" class="logo">
      <img src="Imagens/logo.png" alt="Logo Mentora">
      </a>
      <nav><a href="index.html">Home</a><a href="buscar.html">Buscar professor</a><a href="index.html#como">Como funciona</a></nav>
      <div>${direita}</div>
    </header>`;
}

// ---------- Login e cadastro ----------
async function entrar(evento) {
  evento.preventDefault();
  const f = evento.target;
  try {
    await Api.entrar(f.email.value, f.senha.value);
    window.location.href = "escolha.html";
  } catch (e) { mostrarErro(e); }
}

async function criarConta(evento) {
  evento.preventDefault(); // impede a página de recarregar
  const f = evento.target;
  if (f.senha.value !== f.confirmar.value) { alert("As senhas não são iguais."); return; }
  try {
    await Api.cadastrar(f.nome.value, f.email.value, f.senha.value); // cria a conta e já faz login
    window.location.href = "escolha.html";
  } catch (e) { mostrarErro(e); }
}

// ---------- Professores ----------
let professores = [];   // lista carregada da API (substitui o antigo dados.js)

// A API pode devolver nomes de campos diferentes dos que a tela usa.
// Esta função "traduz" UM professor da API para o formato da tela.
// ⚠ Se algum campo aparecer vazio na tela, confira o nome dele aqui.
function normalizarProfessor(p) {
  const disciplinas = p.disciplinas || [];       // [{id, nome, preco}]
  const preco = p.preco ?? (disciplinas.length ? Math.min(...disciplinas.map(d => Number(d.preco))) : 0);
  return {
    id: p.id_professor ?? p.id,
    nome: p.nome ?? p.professor,
    materia: p.materia ?? (disciplinas[0] ? disciplinas[0].nome : p.disciplina || "—"),
    disciplinas,
    preco,
    nota: p.nota_media ?? p.nota ?? "—",   // null (sem avaliações) vira "—"
    avaliacoes: p.total_avaliacoes ?? p.avaliacoes ?? 0,
    descricao: p.descricao || "",
    tags: p.tags || [...disciplinas.map(d => d.nome), p.modalidade].filter(Boolean)
  };
}

async function carregarProfessores() {
  const dados = await Api.professores();
  professores = (Array.isArray(dados) ? dados : dados.professores || []).map(normalizarProfessor);
  return professores;
}

function cardProfessor(p) {
  return `<div class="card">
    <div class="linha">
      <span class="avatar grande">${esc(p.nome[0])}</span>
      <div class="cresce"><b>${esc(p.nome)}</b><br><small class="laranja">${esc(p.materia)}</small><br><small>⭐ ${esc(p.nota)} (${esc(p.avaliacoes)})</small></div>
      <div class="preco">R$ ${esc(p.preco)}<br><small>/hora</small></div>
    </div>
    <p><small>${esc(p.descricao)}</small></p>
    ${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}
    <a href="perfil-professor.html?id=${p.id}" class="btn btn-largo">Ver perfil</a>
  </div>`;
}

function mostrarProfessores(lista) {
  document.getElementById("lista").innerHTML = lista.map(cardProfessor).join("");
}

// Home: carrega da API e mostra só os 4 primeiros
async function iniciarHome() {
  try {
    await carregarProfessores();
    mostrarProfessores(professores.slice(0, 4));
  } catch (e) {
    document.getElementById("lista").innerHTML = `<p><small>${esc(e.message)}</small></p>`;
  }
}

// ---------- Busca com filtro por matéria ----------
let categoria = "Todos";

// Os botões de matéria agora vêm da tabela "disciplina" do banco
async function montarCategorias() {
  let nomes = ["Todos"];
  try { nomes = nomes.concat((await Api.disciplinas()).map(d => d.nome)); } catch (e) { /* mantém só "Todos" */ }
  document.getElementById("categorias").innerHTML = nomes.map(n =>
    `<button class="chip ${n === "Todos" ? "ativo" : ""}" onclick="escolherCategoria(this, '${esc(n)}')">${esc(n)}</button>`).join("");
}

function escolherCategoria(botao, nome) {
  categoria = nome;
  document.querySelectorAll("#categorias .chip").forEach(c => c.classList.remove("ativo"));
  botao.classList.add("ativo");
  filtrar();
}

// Filtra a lista que já está na memória (não precisa ir ao servidor a cada letra digitada)
function filtrar() {
  const texto = document.getElementById("busca").value.toLowerCase();
  const resultado = professores.filter(p =>
    (categoria === "Todos" || p.disciplinas.some(d => d.nome === categoria) || p.materia === categoria) &&
    (p.nome + " " + p.tags.join(" ")).toLowerCase().includes(texto));
  document.getElementById("total").textContent = resultado.length + " professores encontrados";
  mostrarProfessores(resultado);
}

async function iniciarBusca() {
  if (!exigirLogin()) return;
  montarMenu(true);
  mostrarPerfilAluno();
  montarCategorias();
  try { await carregarProfessores(); filtrar(); } catch (e) { mostrarErro(e); }
  mostrarAulas();
}

// ---------- Abas (mostra uma seção e esconde as outras) ----------
function trocarAba(nome) {
  document.querySelectorAll(".aba").forEach(a => a.classList.remove("ativa"));
  document.getElementById("aba-" + nome).classList.add("ativa");
  document.querySelectorAll(".abas button").forEach(b => b.classList.toggle("ativo", nome.startsWith(b.dataset.aba)));
}

// ---------- Aulas do aluno ----------
let aulasAluno = [];

async function mostrarAulas() {
  try { aulasAluno = await Api.minhasAulas(); } catch (e) { aulasAluno = []; }
  const rotulos = { aguardando: "aguardando professor", agendada: "agendada", aguardando_confirmacao: "confirme a aula",
                    confirmada: "confirmada", recusada: "recusada", cancelada: "cancelada" };
  document.getElementById("aulas").innerHTML = aulasAluno.length === 0
    ? '<div class="card centro"><small>Você ainda não tem aulas.</small></div>'
    : aulasAluno.map(a => `
    <div class="card linha">
      <span class="avatar">${esc((a.professor || "P")[0])}</span>
      <div class="cresce"><b>${esc(a.professor)}</b><br><small>${esc(a.disciplina)} · ${esc(a.rotulo || formatarData(a.data_hora))}</small></div>
      <span class="tag">${esc(rotulos[a.status] || a.status)}</span>
      ${a.pode_confirmar ? `<button class="btn" onclick="confirmarAula(${a.id})">Confirmar aula</button>` : ""}
      ${a.pode_avaliar ? `<button class="btn btn-claro" onclick="avaliarAula(${a.id})">Avaliar</button>` : ""}
    </div>`).join("");
}

async function avaliarAula(id) {
  const nota = prompt("Dê uma nota de 1 a 5 para a aula:");
  if (!nota) return;
  const comentario = prompt("Comentário (opcional):") || "";
  try { await Api.avaliarAula(id, Number(nota), comentario); alert("Obrigado pela avaliação!"); mostrarAulas(); }
  catch (e) { mostrarErro(e); }
}

// O aluno digita o PIN que o professor gerou; a API confere (5 erros invalidam o PIN)
async function confirmarAula(id) {
  const pin = prompt("Digite o PIN de confirmação que o professor te passou:");
  if (!pin) return;
  try {
    await Api.confirmarAula(id, pin);
    alert("Aula confirmada! O pagamento será liberado ao professor.");
    mostrarAulas();       // redesenha a lista já com o novo status
  } catch (e) { mostrarErro(e); }
}

// ---------- Perfil do aluno (buscar.html) ----------
function mostrarPerfilAluno() {
  const u = usuario();
  document.getElementById("ola").textContent = "Olá, " + u.nome.split(" ")[0] + "! 👋";
  document.getElementById("inicial").textContent = u.nome[0];
  document.getElementById("nome").textContent = u.nome;
  document.getElementById("email").textContent = u.email;
  // preenche o formulário de edição com os dados atuais
  document.getElementById("enome").value = u.nome;
  document.getElementById("eemail").value = u.email;
}

async function salvarPerfilAluno(evento) {
  evento.preventDefault();
  try {
    const novo = await Api.salvarMeuUsuario({
      nome: document.getElementById("enome").value,
      email: document.getElementById("eemail").value
    });
    Sessao.salvar(Sessao.token(), { ...usuario(), ...(novo.usuario || novo) }); // atualiza a sessão local
    mostrarPerfilAluno();
    montarMenu(true);   // atualiza a inicial no menu do topo
    alert("Perfil atualizado!");
    trocarAba("perfil");
  } catch (e) { mostrarErro(e); }
}

// ---------- Cadastro do professor (3 etapas) ----------
let etapaAtual = 1;

function irEtapa(n) {
  etapaAtual = n;
  document.querySelectorAll(".etapa").forEach((e, i) => e.style.display = (i + 1 === n) ? "block" : "none");
  document.querySelectorAll(".barra span").forEach((b, i) => b.classList.toggle("feita", i < n));
  document.getElementById("passo").textContent = "Etapa " + n + " de 3";
}

function voltar() {
  if (etapaAtual === 1) window.location.href = "escolha.html";
  else irEtapa(etapaAtual - 1);
}

// Os botões de disciplina do cadastro também vêm do banco (cada um guarda o id da disciplina)
async function montarDisciplinasCadastro() {
  try {
    const lista = await Api.disciplinas();
    document.getElementById("cad-disciplinas").innerHTML = lista.map(d =>
      `<button class="chip" data-id="${d.id}" onclick="this.classList.toggle('ativo')">${esc(d.nome)}</button>`).join("");
  } catch (e) { mostrarErro(e); }
}

// 1) envia os dados em JSON (/professor/cadastro)  2) envia foto e comprovante (/professor/documentos)
async function enviarCadastroProfessor() {
  if (!document.getElementById("autorizo").checked) { alert("Autorize a análise do perfil para continuar."); return; }

  const ids = [...document.querySelectorAll("#cad-disciplinas .chip.ativo")].map(c => Number(c.dataset.id));
  const dias = [...document.querySelectorAll("#cad-dias .chip.ativo")].map(c => c.dataset.dia);
  const preco = Number(document.getElementById("cad-preco").value);
  if (ids.length === 0) { alert("Escolha ao menos uma disciplina."); irEtapa(2); return; }
  if (!preco || preco <= 0) { alert("Informe o valor da aula."); irEtapa(2); return; }

  const dados = {
    formacao: document.getElementById("cad-formacao").value,
    descricao: document.getElementById("cad-descricao").value,
    modalidade: document.getElementById("cad-modalidade").value,
    disciplinas: ids.map(id => ({ id, preco })),   // mesmo valor/hora para todas as disciplinas escolhidas
    // o formulário não pergunta horário: cada dia marcado vira uma faixa padrão
    disponibilidade: dias.map(d => ({ dia_semana: d, hora_inicio: "08:00", hora_fim: "18:00" }))
  };

  try {
    await Api.cadastrarProfessor(dados);
  } catch (e) { mostrarErro(e); return; }

  const foto = document.getElementById("cad-foto").files[0];
  const comprovante = document.getElementById("cad-comprovante").files[0];
  if (foto || comprovante) {
    const form = new FormData();
    if (foto) form.append("foto", foto);
    if (comprovante) form.append("comprovante", comprovante);
    try { await Api.enviarDocumentos(form); }
    catch (e) { alert("Cadastro enviado, mas os arquivos não foram aceitos: " + e.message); }
  }
  window.location.href = "aguardando.html";   // o admin precisa aprovar (status 'pendente')
}

// ---------- Área do professor ----------
let pedidos = [], agenda = [];

async function mostrarPedidos() {
  try { pedidos = await Api.pedidos(); } catch (e) { pedidos = []; }
  document.getElementById("pedidos").innerHTML = pedidos.length === 0
    ? '<div class="card centro"><small>Nenhuma solicitação.</small></div>'
    : pedidos.map(p => {
        const id = p.id;
        return `
    <div class="card">
      <div class="linha"><span class="avatar">${esc(p.aluno[0])}</span>
        <div><b>${esc(p.aluno)}</b><br><small>${esc(p.disciplina || p.materia)} · ${esc(p.rotulo || formatarData(p.data_hora))}</small>
        ${p.valor ? `<br><b class="laranja">R$ ${esc(p.valor)}</b>` : ""}</div></div>
      ${p.status === "pendente"
        ? `<div class="linha" style="margin-top:12px">
             <button class="btn btn-claro cresce" onclick="responder(${id}, 'recusar')">✗ Recusar</button>
             <button class="btn cresce" onclick="responder(${id}, 'aceitar')">✓ Aceitar</button></div>`
        : `<span class="tag">${p.status === "aceita" ? "Aceita" : "Recusada"}</span>`}
    </div>`; }).join("");
  const pendentes = pedidos.filter(p => p.status === "pendente").length;
  document.querySelectorAll(".contador").forEach(e => e.textContent = pendentes);
}

async function responder(id, acao) {
  try { await Api.responderPedido(id, acao); mostrarPedidos(); mostrarPainel(); } catch (e) { mostrarErro(e); }
}

// Carrega TUDO do painel do professor de uma vez, em paralelo (Promise.all = mais rápido)
async function mostrarPainel() {
  if (!exigirLogin()) return;
  const [ag, pag, pn] = await Promise.all([
    Api.agenda().catch(() => []),
    Api.pagamentos().catch(() => []),
    Api.painel().catch(() => ({}))
  ]);
  agenda = ag;

  // números dos cards do início (antes eram fixos no HTML)
  document.getElementById("st-aulas").textContent = pn.aulas_mes ?? pn.aulas ?? 0;
  document.getElementById("st-ganhos").textContent = "R$ " + (pn.ganhos_mes ?? pn.ganhos ?? 0);
  document.getElementById("st-nota").textContent = (pn.nota ?? "—") + " ⭐";
  document.getElementById("st-alunos").textContent = pn.alunos_ativos ?? pn.alunos ?? 0;

  // a mesma lista serve para "Próximas aulas" (Início) e para a Agenda
  const lista = agenda.map(a => `
    <div class="card linha">
      <b class="laranja">${esc(a.rotulo || formatarData(a.data_hora))}</b>
      <div class="cresce"><b>${esc(a.aluno)}</b><br><small>${esc(a.disciplina || a.materia)}</small></div>
      <a href="#" class="laranja" onclick="gerarPin(${a.id_aula ?? a.id}); return false;">PIN →</a>
    </div>`).join("") || '<div class="card centro"><small>Nenhuma aula agendada.</small></div>';
  document.getElementById("proximas").innerHTML = lista;
  document.getElementById("agenda").innerHTML = lista;

  document.getElementById("pagamentos").innerHTML = pag.map(p => `
    <div class="card linha">
      <span class="avatar">${esc(p.aluno[0])}</span>
      <div class="cresce"><b>${esc(p.aluno)}</b><br><small>${esc(p.rotulo || "")} · R$ ${esc(p.valor)}</small></div>
      <span class="tag">${esc(p.status)}</span>
    </div>`).join("") || '<div class="card centro"><small>Sem pagamentos.</small></div>';

  mostrarPedidos();
  mostrarPerfilProfessor();
  mostrarDisciplinas();
  mostrarNotificacoes();
}

// Pede à API um PIN novo para uma aula. O professor passa esse PIN ao aluno, que o digita para confirmar.
// Sem id (botão geral do início), usa a primeira aula da agenda.
async function gerarPin(id) {
  id = id ?? (agenda[0] && (agenda[0].id_aula ?? agenda[0].id));
  if (!id) { alert("Você não tem aulas agendadas para gerar PIN."); return; }
  try {
    const r = await Api.gerarPin(id);
    alert("PIN de confirmação: " + r.pin + "\nPasse este código ao aluno ao final da aula.");
  } catch (e) { mostrarErro(e); }
}

// ---------- Perfil do professor (professor.html) ----------
let perfilProf = { nome: "", descricao: "", disciplinas: [] };

async function mostrarPerfilProfessor() {
  try { perfilProf = await Api.perfilProf(); } catch (e) { return; }
  const nome = perfilProf.nome || usuario().nome;
  const materia = (perfilProf.disciplinas || []).map(d => d.nome).join(", ") || "—";
  document.querySelectorAll(".p-nome").forEach(e => e.textContent = nome);
  document.querySelectorAll(".p-materia").forEach(e => e.textContent = materia);
  document.querySelectorAll(".p-inicial").forEach(e => e.textContent = nome[0]);
  document.getElementById("pe-nome").value = nome;
  document.getElementById("pe-bio").value = perfilProf.descricao || "";
  mostrarDisciplinas();
}

async function salvarPerfilProfessor(evento) {
  evento.preventDefault();
  try {
    await Api.salvarPerfilProf({
      nome: document.getElementById("pe-nome").value,
      descricao: document.getElementById("pe-bio").value
    });
    await mostrarPerfilProfessor();
    alert("Perfil atualizado!");
    trocarAba("perfil");
  } catch (e) { mostrarErro(e); }
}

// Minhas disciplinas: clicar marca/desmarca e grava no banco (tabela professor_disciplina)
let todasDisciplinas = [];

async function mostrarDisciplinas() {
  if (todasDisciplinas.length === 0) { try { todasDisciplinas = await Api.disciplinas(); } catch (e) { return; } }
  const minhas = (perfilProf.disciplinas || []).map(d => d.id);
  document.getElementById("disciplinas").innerHTML = todasDisciplinas.map(d =>
    `<button class="chip ${minhas.includes(d.id) ? "ativo" : ""}" onclick="alternarDisciplina(${d.id}, ${minhas.includes(d.id)})">${esc(d.nome)}</button>`).join("");
}

async function alternarDisciplina(id, jaTem) {
  try {
    // a API troca a lista inteira de uma vez: montamos a lista nova e enviamos
    let lista = (perfilProf.disciplinas || []).map(d => ({ id: d.id, preco: d.preco }));
    if (jaTem) {
      lista = lista.filter(d => d.id !== id);
    } else {
      const preco = Number((prompt("Qual o valor da sua hora/aula nesta disciplina (R$)?") || "").replace(",", "."));
      if (!preco) return;
      lista.push({ id, preco });
    }
    await Api.salvarDisciplinasProf(lista);
    await mostrarPerfilProfessor();
  } catch (e) { mostrarErro(e); }
}

// Notificações: mostra a lista ou uma mensagem se não houver nenhuma
async function mostrarNotificacoes() {
  let itens = [], naoLidas = 0;
  try { const r = await Api.notificacoes(); itens = r.itens || []; naoLidas = r.nao_lidas || 0; } catch (e) { /* lista vazia */ }
  document.getElementById("qtdNotif").textContent = naoLidas ? " (" + naoLidas + ")" : "";
  document.getElementById("notificacoes").innerHTML = itens.length === 0
    ? '<div class="card centro"><small>Nenhuma notificação por enquanto.</small></div>'
    : itens.map(n => `
        <div class="card">🔔 ${n.lida ? esc(n.texto) : "<b>" + esc(n.texto) + "</b>"}<br><small>${esc(n.quando || "")}</small></div>`).join("");
  if (naoLidas) Api.lerNotificacoes().catch(() => {});   // marca como lidas depois de mostrar
}

// ---------- Perfil do professor visto pelo aluno (perfil-professor.html) ----------
let horarioEscolhido = null;   // guarda o horário {data_hora, rotulo...} do chip clicado
let professorAtual = null;

async function mostrarPerfilDoProfessor() {
  const id = new URLSearchParams(window.location.search).get("id");  // vem da URL: ?id=3
  try {
    const [bruto, horarios] = await Promise.all([Api.professor(id), Api.horarios(id).catch(() => [])]);
    const p = professorAtual = normalizarProfessor(bruto);
    document.getElementById("conteudo").innerHTML = `
    <div class="card">
      <div class="linha">
        <span class="avatar grande">${esc(p.nome[0])}</span>
        <div class="cresce"><h2 style="margin:0">${esc(p.nome)}</h2><small class="laranja">${esc(p.materia)}</small><br><small>⭐ ${esc(p.nota)} (${esc(p.avaliacoes)} avaliações)</small></div>
        <div class="preco">R$ ${esc(p.preco)}<br><small>/hora</small></div>
      </div>
      <h3>Sobre</h3>
      <p><small>${esc(p.descricao)}</small></p>
      ${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}
    </div>
    <div class="card">
      <h3>Disciplina</h3>
      <select id="sel-disciplina">
        ${p.disciplinas.map(d => `<option value="${d.id}">${esc(d.nome)} — R$ ${esc(d.preco)}/h</option>`).join("")}
      </select>
      <h3>Horários disponíveis</h3>
      ${horarios.map((h, i) => `<button class="chip" onclick="escolherHorario(this, ${i})">${esc(h.rotulo)}</button>`).join("") || "<small>Sem horários livres nos próximos dias.</small>"}
      <button class="btn btn-largo" style="width:100%" onclick="solicitarAula()">Solicitar aula</button>
    </div>`;
    window.horariosProfessor = horarios;   // guarda para o clique achar o horário pelo índice
  } catch (e) {
    document.getElementById("conteudo").innerHTML = "<p>Professor não encontrado.</p>";
  }
}

function escolherHorario(botao, i) {
  horarioEscolhido = window.horariosProfessor[i];
  document.querySelectorAll("#conteudo .chip").forEach(c => c.classList.remove("ativo"));
  botao.classList.add("ativo");
}

async function solicitarAula() {
  if (!Sessao.logado()) { window.location.href = "login.html"; return; }   // só aluno logado solicita
  if (!horarioEscolhido) { alert("Escolha um horário primeiro."); return; }
  try {
    await Api.solicitarAula({
      id_professor: professorAtual.id,
      id_disciplina: Number(document.getElementById("sel-disciplina").value),
      data_hora: horarioEscolhido.data_hora   // já vem pronto da API (ex.: 2026-11-02T19:00:00)
    });
    alert("Solicitação enviada para " + professorAtual.nome + ". Aguarde a resposta do professor.");
    window.location.href = "buscar.html";
  } catch (e) { mostrarErro(e); }
}