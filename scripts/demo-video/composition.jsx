import React from 'react';
import {AbsoluteFill, Audio, Composition, Img, OffthreadVideo, Sequence, registerRoot, staticFile, useCurrentFrame} from 'remotion';

function Demo({clips, audio, totalFrames}) {
  const frame = useCurrentFrame();
  const active = clips.find(clip => frame >= clip.start && frame < clip.start + clip.frames) || clips[0];
  return <AbsoluteFill style={{background:'#171d1b',fontFamily:'PingFang SC, sans-serif',color:'#f6f8f7'}}>
    <div style={{height:88,display:'flex',alignItems:'center',padding:'0 42px',gap:24,borderBottom:'1px solid #415249'}}>
      <span style={{fontSize:28,fontWeight:700,color:'#bed600'}}>Specialist OS</span>
      <span style={{fontSize:25}}>{active.title}</span>
      <span style={{marginLeft:'auto',fontSize:19,color:'#a8beb1'}}>本地 CLI 实录 · 1×</span>
    </div>
    <div style={{position:'absolute',top:88,left:160,width:1600,height:900}}>
      {clips.map(clip=><Sequence key={clip.id} from={clip.start} durationInFrames={clip.frames}>
        <OffthreadVideo muted src={staticFile(clip.src)} style={{width:'100%',height:'100%',objectFit:'contain'}} />
      </Sequence>)}
    </div>
    <div style={{position:'absolute',bottom:0,height:72,left:0,right:0,display:'flex',alignItems:'center',padding:'0 42px',fontSize:23,background:'#28624a'}}>{active.caption}</div>
    {audio.map((clip,index)=><Sequence key={index} from={clip.start} durationInFrames={clip.frames}>
      <Audio src={staticFile(clip.src)} startFrom={clip.sourceStart} volume={0.8}/>
    </Sequence>)}
    <div style={{position:'absolute',bottom:0,left:0,height:4,width:`${frame/totalFrames*100}%`,background:'#bed600'}}/>
  </AbsoluteFill>;
}
registerRoot(()=> <Composition id="SpecialistDemo" component={Demo} width={1920} height={1080} fps={30} durationInFrames={300} defaultProps={{clips:[],audio:[],totalFrames:300}} calculateMetadata={({props})=>({durationInFrames:props.totalFrames})}/>);
