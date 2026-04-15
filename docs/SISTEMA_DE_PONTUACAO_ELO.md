# Sistema de Pontuação ELO - Patota Ajax

Este documento descreve as regras matemáticas por trás do sistema "MatchEngine" do Sorteador Ajax. A lógica de balanceamento e distribuição de pontos pós-jogo baseia-se no **Sistema ELO original** (utilizado pela FIFA e pela Federação Internacional de Xadrez).

---

## 1. O Ponto de Partida (1000)
- Todos os novos jogadores da Patota (incluindo visitantes sem force de nota manual) que nunca jogaram antes **iniciam com uma nota padrão de 1000 pontos**.
- A nota representa o "Nível de Habilidade" (Rating) de um atleta na quadra. Na divisão inicial, o App tenta que as duas equipes somem pontuações o mais parecidas possível.

---

## 2. Jogo de "Soma Zero" (Rouba Monte)
O sistema ELO não "imprime" e não cria novos pontos do nada. A pontuação é uma **Transferência Econômica Pura**. 
Para que um jogador vencedor receba `+20 pontos` na sua ficha, os `20 pontos` terão que sair do bolso dos jogadores que perderam.
- Se o seu time vence: você tira pontos dos jogadores do time oponente.
- Se o seu time perde: os seus pontos são extraídos e doados para o oponente.

---

## 3. Punição por Goleada (K-Factor)
O **K-Factor** na matemática de IA diz respeito ao "Peso do Evento". No nosso app, a diferença (saldo) de gols muda o peso do jogo drasticamente.
* `K = 32` **(Jogos Empatados ou Decididos por 1 a 2 gols):** Considerado um jogo de ritmo normal. As transferências de pontos oscilam num teto máximo baixo.
* `K = 48` **(Vitória Clara, por 3 a 4 gols):** O impacto na nota aumenta em 50%. A punição para quem joga de corpo mole é mais severa.
* `K = 64` **(Goleadas Históricas, 5 gols ou mais):** Impacto violento. As variações podem ser altíssimas, rebaixando seriamente jogadores que foram humilhados e promovendo rapidamente bons jogadores que destruíram a defesa adversária.

---

## 4. Probabilidade e Efeito "Zebra" (Exemplo Prático)
O verdadeiro motor de inteligência da Patota é que o prêmio **não é fixo**. Ele depende da avaliação antes de a bola rolar: a **Expectativa vs. Realidade**.

**Cenário A: "Panela" vs Perna de Paus**
Se a média do Time Azul for absurdamente alta (Favoritos = 1200 pontos de força) contra o Roxo (Azarões = 850 pontos de força):
- **Se o Azul Ganha:** O Azul só fez o que era óbvio. A IA transfere **apenas uns 3 ou 4 pontos** para eles. O Time Roxo perde pouco porque já era esperado perder.
- **Se o Roxo Ganha (ZEBRA ESTOURANDO):** A IA entende que o Roxo fez um milagre esportivo e que o Azul pipocou. Há a maior transferência possível. Jogadores do Azul podem **perder mais de 40 pontos de uma vez só**, e os do Roxo pulam no ranking ganhando o prêmio todo.

---

## 5. Notas dos Visitantes
O App não grava visitantes permanentemente de imediato pela interface de presenças para evitar sujeira de base.
Entretanto, o Organizador tem em mãos o **Slider (Nível da Fera)** ao inserir visitantes. O Slider engana momentaneamente a IA antes do Sorteio para forçar pesos diferentes e impedir desequilíbrio:
* Nível 1: `850` (Péssimo)
* Nível 2: `925` (Ruim)
* Nível 3: `1000` (Médio - Padrão)
* Nível 4: `1075` (Bom Nível)
* Nível 5: `1150` (Craque Visitante)

Essa mecânica permite domar perfeitamente a equipe inicial antes de colocar a bola no chão.
