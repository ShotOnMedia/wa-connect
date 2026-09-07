// Formats packed User Input condition values stored as "answer_key\u001fcomparison".
export function userInputConditionSummary(value, operatorLabel) {
  const raw=String(value||''),i=raw.indexOf('\u001f')
  const key=(i<0?raw:raw.slice(0,i)).trim(),compare=(i<0?'':raw.slice(i+1)).trim(),op=operatorLabel||'is'
  if(op==='is empty'||op==='is not empty')return `User Input: ${key||'answer'} ${op}`
  return `User Input: ${key||'answer'} ${op}${compare?` “${compare}”`:''}`
}
