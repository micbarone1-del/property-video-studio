// Test: overlapping editJob() calls must leave exactly one coherent job loaded.
const fs = require("fs");
function extract(path) {
  const s = fs.readFileSync(path, "utf8");
  const a = s.indexOf("async function editJob(jobId, baseJobId) {");
  const pre = s.lastIndexOf("let _editJobSeq", a) > a - 200 ? s.lastIndexOf("let _editJobSeq", a) : a;
  const b = s.indexOf("// ── Generation pause / kill-switch", a);
  return s.slice(pre, b);
}
async function run(path, delays) {
  const code = extract(path);
  const harness = `
    let files = [], sceneUserData = {}, completedScenes = [], currentJobId=null, currentJobStatus=null, narrationExistsOnServer=false, narrationDistribution=null;
    const newlyAddedSceneIndices = new Set(), durationChangedSceneIndices = new Set(), contentChangedSceneIndices = new Set(), sceneAnalysis = {};
    const scenesCont = {replaceChildren(){}}; const qcSec = {style:{}};
    const el = () => ({style:{}, value:"", textContent:"", innerHTML:"", scrollIntoView(){}});
    const document = {getElementById: () => el()};
    function renderScenes(){ RENDERED.push(files.length); } function closeJobPreview(){} function updateCostEstimate(){} function showError(){} function showQcReview(){}
    const RENDERED = [];
    async function authFetch(url){
      const m = url.match(/^\\/jobs\\/([^/?]+)(\\/image\\/(\\d+))?/);
      await new Promise(r => setTimeout(r, DELAYS[m[1]] || 1));
      if (m[2]) return {ok:true, blob: async()=>({type:"image/jpeg"})};
      return {json: async()=>({status:"draft", scenes:[], scenes_config: Array.from({length:6},(_,i)=>({space_type:"large",duration:5}))})};
    }
    ${code}
    (async()=>{ await Promise.all([editJob("A","A"), editJob("B","B")]); return {files: files.length, keys: Object.keys(sceneUserData).length, rendered: RENDERED}; })()
  `;
  return await eval("(function(DELAYS){ return " + "(async()=>{ " + harness.replace(/\(async\(\)=>\{ await Promise\.all[\s\S]*$/, "") + " return await (async()=>{ await Promise.all([editJob('A','A'), editJob('B','B')]); return {files: files.length, keys: Object.keys(sceneUserData).length, rendered: RENDERED}; })(); })(); })")(delays);
}
(async () => {
  let ok = true;
  const t = (name, cond) => { console.log((cond ? "PASS " : "FAIL ") + name); if (!cond) ok = false; };
  const after = await run("ui.html", {A: 3, B: 1});
  t("NEW code: 6 files, 6 scene entries -> " + JSON.stringify(after), after.files === 6 && after.keys === 6);
  const after2 = await run("ui.html", {A: 1, B: 3});
  t("NEW code, reversed timing -> " + JSON.stringify(after2), after2.files === 6 && after2.keys === 6);
  t("NEW code renders only once for the latest call", after.rendered.length === 1 && after2.rendered.length === 1);
  console.log(ok ? "ALL PASS" : "SOME FAIL"); process.exit(ok ? 0 : 1);
})();
