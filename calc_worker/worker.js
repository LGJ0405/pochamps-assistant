/**
 * worker.js
 * @smogon/calc 래핑 워커 — Python에서 JSON 요청을 받아 계산 결과를 반환
 *
 * 사용법:
 *   node calc_worker/worker.js
 *   stdin으로 JSON 한 줄 입력 → stdout으로 JSON 한 줄 출력
 *
 * 요청 형식:
 *   { "attacker": {...}, "defender": {...}, "move": "...", "field": {...} }
 *
 * 응답 형식:
 *   { "ok": true, "result": { "damage": [...], "desc": "...", ... } }
 *   { "ok": false, "error": "..." }
 */

"use strict";

const { Generations, Pokemon, Move, Field, calculate } = require("@smogon/calc");
const readline = require("readline");

// 9세대(SV) 기본, 필요 시 요청에서 gen 지정 가능
const DEFAULT_GEN = 9;

/**
 * JSON 요청으로부터 Pokemon 객체 생성
 */
function buildPokemon(gen, data) {
  const opts = {
    level: data.level || 50,
    item: data.item,
    ability: data.ability,
    nature: data.nature,
    evs: data.evs,
    ivs: data.ivs,
    boosts: data.boosts,
    status: data.status,
    curHP: data.curHP,
  };

  return new Pokemon(gen, data.species, opts);
}

/**
 * 데미지 계산 실행
 */
function runCalc(request) {
  const genNum = request.gen || DEFAULT_GEN;
  const gen = Generations.get(genNum);

  const attacker = buildPokemon(gen, request.attacker);
  const defender = buildPokemon(gen, request.defender);
  const move = new Move(gen, request.move);
  const field = request.field ? new Field(request.field) : new Field();

  const result = calculate(gen, attacker, defender, move, field);

  // 0배 무효 상성 체크 (damage가 0이거나 모든 난수가 0인 경우)
  const isZero = Array.isArray(result.damage)
    ? (result.damage.length > 0 && result.damage[result.damage.length - 1] === 0)
    : result.damage === 0;

  let desc = "";
  let fullDesc = "";
  let moveDesc = "";

  if (isZero) {
    try {
      // err=false 옵션으로 throw 방지
      const baseDesc = result.fullDesc("%", false);
      desc = `${baseDesc} -- 효과 없음`;
      fullDesc = `${baseDesc} -- 효과 없음`;
    } catch (_) {
      desc = `${attacker.name} ${move.name} vs. ${defender.name}: 0-0 (0 - 0%) -- 효과 없음`;
      fullDesc = desc;
    }
    moveDesc = "0 - 0% (효과 없음)";
  } else {
    try {
      desc = result.desc();
      fullDesc = result.fullDesc();
      moveDesc = result.moveDesc();
    } catch (_) {
      desc = result.fullDesc("%", false);
      fullDesc = desc;
      moveDesc = result.moveDesc();
    }
  }

  return {
    ok: true,
    result: {
      damage: Array.isArray(result.damage) ? result.damage : [result.damage],
      desc: desc,
      fullDesc: fullDesc,
      moveDesc: moveDesc,
      // 추가 메타정보
      attacker: {
        species: attacker.name,
        stats: attacker.rawStats,
      },
      defender: {
        species: defender.name,
        stats: defender.rawStats,
      },
    },
  };
}

// ── REPL: stdin에서 줄 단위 JSON 읽기 ──
const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let response;
  try {
    const request = JSON.parse(trimmed);
    response = runCalc(request);
  } catch (err) {
    response = { ok: false, error: err.message || String(err) };
  }
  process.stdout.write(JSON.stringify(response) + "\n");
});

rl.on("close", () => {
  process.exit(0);
});
