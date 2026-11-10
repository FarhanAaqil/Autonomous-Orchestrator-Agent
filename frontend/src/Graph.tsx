import { Component, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Canvas } from '@react-three/fiber';
import type { Agent } from './api';
class Boundary extends Component<{children: ReactNode}, {failed: boolean}> {
  state = {failed: false};
  static getDerivedStateFromError() {return {failed: true};}
  render() {return this.state.failed ? <p className="banner">3D is unavailable. Every agent and its state remains in the list below.</p> : this.props.children;}
}
function Scene({agents}: {agents: Agent[]}) {
  return <><ambientLight intensity={1.8}/><directionalLight position={[3,5,4]} intensity={3}/>
    <mesh rotation={[.25,.3,.1]}><torusGeometry args={[1.5,.045,12,64]}/><meshStandardMaterial color="#a8885b" roughness={.5}/></mesh>
    <mesh rotation={[.1,.3,-.1]}><boxGeometry args={[.85,.85,.85]}/><meshStandardMaterial color="#ac5939" roughness={.4}/></mesh>
    {agents.slice(0,20).map((agent,i) => {const angle = i / Math.min(agents.length,20) * Math.PI * 2; return <mesh key={agent.id} position={[Math.cos(angle)*1.65,Math.sin(angle)*1.4,Math.sin(angle*2)*.4]}><sphereGeometry args={[.17,20,16]}/><meshStandardMaterial color={agent.is_active ? '#8c966b' : '#ab8066'} roughness={.35}/></mesh>;})}
  </>;
}
export default function Graph({agents}: {agents: Agent[]}) {
  const [hidden, setHidden] = useState(document.hidden);
  useEffect(() => {const change = () => setHidden(document.hidden); document.addEventListener('visibilitychange', change); return () => document.removeEventListener('visibilitychange', change);}, []);
  return <Boundary><div className="graph-panel" role="img" aria-label="Agent constellation. The center represents this workspace; surrounding nodes represent enabled and disabled agents, listed in full below."><span className="graph-caption">Your workspace constellation ? {agents.length} agents<br/>Olive: enabled ? clay: disabled ? Full details below</span>{!hidden && <Canvas frameloop="demand" dpr={[1,1.5]} camera={{position:[0,0,5.8],fov:43}} gl={{antialias:true,powerPreference:'low-power'}} fallback={<p>WebGL is unavailable. Use the agent list below.</p>} onCreated={({gl}) => gl.domElement.addEventListener('webglcontextlost', event => {event.preventDefault(); setHidden(true);}, {once:true})}><Scene agents={agents}/></Canvas>}</div></Boundary>;
}
