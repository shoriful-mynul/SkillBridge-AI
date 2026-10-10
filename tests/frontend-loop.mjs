// Handler/state contract test; this is not browser visual or DOM verification.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module,{createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const ts=require('typescript'),React=require('react');
const root=path.resolve(path.dirname(new URL(import.meta.url).pathname),'..');
let fixture=JSON.parse(fs.readFileSync(path.join(root,'public/rehearsal/ai-ml-intern.json'),'utf8'));
const source=fs.readFileSync(path.join(root,'app/workspace.tsx'),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const reportCode=ts.transpileModule(fs.readFileSync(path.join(root,'app/report.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const reportMod=new Module(path.join(root,'app/report'));reportMod.filename=path.join(root,'app/report');reportMod.paths=Module._nodeModulePaths(path.join(root,'app'));reportMod._compile(reportCode,reportMod.filename);require.cache[path.join(root,'app/report')]=reportMod;
const compiled=new Module(path.join(root,'app/workspace-test.cjs'));
compiled.filename=path.join(root,'app/workspace-test.cjs');
compiled.paths=Module._nodeModulePaths(path.join(root,'app'));
const originalLoad=Module._load;Module._load=function(id,parent,...rest){if(id==='./report'&&parent?.filename===compiled.filename)return reportMod.exports;return originalLoad.call(this,id,parent,...rest);};
compiled._compile(code,compiled.filename);Module._load=originalLoad;
const Workspace=compiled.exports.default;
function nodes(tree){if(!tree||typeof tree!=='object')return [];if(Array.isArray(tree))return tree.flatMap(nodes);return [tree,...nodes(tree.props?.children)];}
function text(tree){if(tree===null||tree===undefined||typeof tree==='boolean')return '';if(typeof tree!=='object')return String(tree);if(Array.isArray(tree))return tree.map(text).join('');return text(tree.props?.children);}

for(const roleId of ['ai-ml-intern','data-analyst-intern','frontend-developer-intern'])test('frontend rehearsal flow: '+roleId,async()=>{
 fixture=JSON.parse(fs.readFileSync(path.join(root,'public/rehearsal/'+roleId+'.json'),'utf8'));
 const oldState=React.useState,oldEffect=React.useEffect,oldFetch=globalThis.fetch,oldWindow=globalThis.window;
 const values=[];let cursor=0,tree;
 React.useState=initial=>{const index=cursor++;if(!(index in values))values[index]=typeof initial==='function'?initial():initial;return [values[index],next=>{values[index]=typeof next==='function'?next(values[index]):next;}];};
 React.useEffect=()=>{};
 globalThis.window={scrollTo(){}};
 globalThis.fetch=async url=>{assert.equal(url,'/rehearsal/'+roleId+'.json');return {ok:true,json:async()=>structuredClone(fixture)};};
 const render=()=>{cursor=0;tree=Workspace();return tree;};
 const findButton=label=>{const found=nodes(tree).find(n=>n.type==='button'&&text(n).trim()===label);assert.ok(found,`Button ${label} exists`);assert.equal(!!found.props.disabled,false,`Button ${label} is enabled`);return found;};
 const click=async label=>{await findButton(label).props.onClick();render();};
 try{
  render();const roleSelect=nodes(tree).find(n=>n.type==='select'&&n.props.id==='target-role');roleSelect.props.onChange({target:{value:roleId}});render();await click('Explore synthetic rehearsal');
  assert.match(text(tree),/Synthetic rehearsal · not live AI/);
  assert.ok(text(tree).includes(fixture.records[0].task.grounding_quotes[1]));
  await click('Load first sample answer');await click('Review illustrative evidence →');
  assert.match(text(tree),/Coachability is pending your revision/);
  assert.match(text(tree),/Partially evidenced/);
  await click('Load sample probe answers');await click('See illustrative confidence →');
  assert.match(text(tree),/high confidence in this explanation/);
  assert.match(text(tree),/Nerves, time pressure/);
  const choice=nodes(tree).find(n=>n.type==='input'&&n.props.name==='practice');assert.ok(choice);choice.props.onChange();render();
  await click('Revise with my chosen step ↗');await click('Load revised sample answer');await click('Review illustrative evidence →');
  assert.ok(text(tree).includes(fixture.records[2].delta.before+' → '+fixture.records[2].delta.after));
  assert.match(text(tree),/Evidenced on this task/);
  await click('Load sample probe answers');await click('See illustrative confidence →');
  assert.ok(text(tree).includes(fixture.records[2].delta.before+' → '+fixture.records[2].delta.after));
  assert.match(text(tree),/Attempt 2/);
  assert.ok(nodes(tree).some(n=>n.type==='button'&&text(n)==='Start another session →'));
  const projectNav=nodes(tree).find(n=>n.type==='button'&&text(n).includes('Your project'));assert.ok(projectNav);projectNav.props.onClick();render();
  const input=nodes(tree).find(n=>n.type==='textarea'&&n.props.id==='cv');assert.ok(input);input.props.onChange({target:{value:'My own Python project description with a concrete preprocessing choice.'}});render();
  assert.doesNotMatch(text(tree),/Synthetic rehearsal · not live AI/);
  assert.ok(nodes(tree).some(n=>n.type==='textarea'&&n.props.id==='cv'&&n.props.value.startsWith('My own Python project')));
 }finally{React.useState=oldState;React.useEffect=oldEffect;globalThis.fetch=oldFetch;globalThis.window=oldWindow;}
});

test('Understand my project validates inputs and sends a live request even after an unconfigured health check',async()=>{
 const oldState=React.useState,oldEffect=React.useEffect,oldFetch=globalThis.fetch,oldWindow=globalThis.window;
 const values=[];let cursor=0,tree,calls=0;
 React.useState=initial=>{const index=cursor++;if(!(index in values))values[index]=typeof initial==='function'?initial():initial;return [values[index],next=>{values[index]=typeof next==='function'?next(values[index]):next;}];};React.useEffect=()=>{};globalThis.window={scrollTo(){}};
 globalThis.fetch=async(url,options)=>{assert.equal(url,'/api/backend/api/assessments');const body=JSON.parse(options.body);assert.equal(body.consent,true);assert.equal(body.role_id,'ai-ml-intern');assert.ok(body.text.length>=40);calls++;return {ok:false,json:async()=>({error:{message:'Missing GEMINI_API_KEY. Configure the server secret.'}})};};
 const render=()=>{cursor=0;tree=Workspace();};const btn=()=>nodes(tree).find(n=>n.type==='button'&&text(n)==='Understand my project →');
 try{render();assert.equal(btn().props.disabled,false);await btn().props.onClick();render();assert.match(text(tree),/at least 40 characters/);assert.equal(calls,0);nodes(tree).find(n=>n.type==='textarea'&&n.props.id==='cv').props.onChange({target:{value:'I built a React form using local state and chose inline validation for clear feedback.'}});render();await btn().props.onClick();render();assert.match(text(tree),/consent checkbox/);assert.equal(calls,0);nodes(tree).find(n=>n.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:true}});render();await btn().props.onClick();render();assert.equal(calls,1);assert.match(text(tree),/Missing GEMINI_API_KEY/);assert.ok(nodes(tree).find(n=>n.type==='textarea'&&n.props.id==='cv').props.value.includes('React form'));}finally{React.useState=oldState;React.useEffect=oldEffect;globalThis.fetch=oldFetch;globalThis.window=oldWindow;}
});
