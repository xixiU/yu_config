// Clash Verge 全局扩展脚本 - 修正版
// 功能：自动提取节点，按国家分组，并开启 Provider 抓取

function main(config) {
  
  
  // 防止配置为空的保护措施
  if (!config['proxy-groups']) config['proxy-groups'] = [];
  if (!config['rules']) config['rules'] = [];
  const providers = {
    "adrules_domain": {
      "type": "http",
      "behavior": "domain", // 声明为域名集模式，效率最高
      "url": "https://fastly.jsdelivr.net/gh/Cats-Team/AdRules@main/adrules_domainset.txt",
      "path": "./ruleset/adrules_domain.yaml",
      "interval": 86400
    },
    "reject": {
      "type": "http",
      "behavior": "domain",
      "url": "https://fastly.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/reject.txt",
      "path": "./ruleset/reject.yaml",
      "interval": 86400
    },
    "advertising": {
      "type": "http",
      "behavior": "domain",
      "url": "https://fastly.jsdelivr.net/gh/ACL4SSR/ACL4SSR@master/Clash/Providers/BanAD.yaml",
      "path": "./ruleset/advertising.yaml",
      "interval": 86400
    }
  };
  config['rule-providers'] = { ...config['rule-providers'], ...providers };
  // --- 1. 定义筛选规则 (正则表达式) ---
  
  // AI 组：匹配 美国(US) 或 日本(JP) 相关的节点
  // (?i) 表示不区分大小写
  const aiFilter = "(?i)(美国|US|United States|America|日本|JP|Japan|Tokyo|Osaka)";
  
  // GitHub 组：匹配 香港(HK) 或 新加坡(SG) 相关的节点
  const githubFilter = "(?i)(香港|HK|Hong Kong|新加坡|SG|Singapore|Lion City)";

  // --- 2. 定义新的策略组 ---
  
  const adBlockGroup = {
    "name": "🚫 广告拦截",
    "type": "select",
    "proxies": ["REJECT", "DIRECT"] // 默认拒绝，如果误杀可以手动切回 DIRECT
  };

  const newGroups = [
    adBlockGroup,
    {
      "name": "🐙 GitHub",
      "type": "select",
      "proxies": [],
      // 【关键修正】开启此选项，让组可以读取订阅文件(Provider)里的节点
      "include-all-providers": true, 
      // 如果不是用 Provider 模式，这行确保能读到散装节点
      "include-all": true,
      "filter": githubFilter
    },
    {
      "name": "🤖 AI 模型",
      "type": "select",
      "proxies": [], // 可以在这里加个 "🚀 节点选择" 指向其他组，但通常 DIRECT 够了
      // 【关键修正】
      "include-all-providers": true,
      "include-all": true,
      "filter": aiFilter
    }
  ];

  // --- 3. 定义分流规则 ---

  const newRules = [
     // 讯飞直连
    "DOMAIN-SUFFIX,iflytek.com,DIRECT",
    "DOMAIN-SUFFIX,iflytek.cn,DIRECT",
    "DOMAIN-SUFFIX,imds.ai,DIRECT",
    "DOMAIN-SUFFIX,rp.iflytek.cn,DIRECT",
    "DOMAIN-SUFFIX,in.iflyaicloud.com,DIRECT",
    "DOMAIN-KEYWORD,ifly,DIRECT",
    "DOMAIN-KEYWORD,iflytek,DIRECT",


    // === 第一优先级：广告拦截 (规则集) ===
    "RULE-SET,adrules_domain,🚫 广告拦截",
    "RULE-SET,reject,🚫 广告拦截",
    "RULE-SET,advertising,🚫 广告拦截",
    
    // 针对腾讯/微信/字节广告的补充规则 (解决国内 App 开屏广告)
    "DOMAIN-KEYWORD,adservice,🚫 广告拦截",
    "DOMAIN-SUFFIX,gdt.qq.com,🚫 广告拦截", // 腾讯广点通
    "DOMAIN-SUFFIX,pglstatp.com,🚫 广告拦截", // 字节跳动广告
    "DOMAIN-SUFFIX,ad.wechat.com,🚫 广告拦截", // 微信广告
    "DOMAIN-KEYWORD,log.umsns.com,🚫 广告拦截", // 微信埋点统计

    // 腾讯广点通 (最核心的广告来源)
    "DOMAIN-SUFFIX,gdt.qq.com,REJECT",
    "DOMAIN-SUFFIX,l.qq.com,REJECT",
    "DOMAIN-SUFFIX,v.gdt.qq.com,REJECT",

    // 腾讯统计与行为分析 (拦截后可减少精准推送)
    "DOMAIN-SUFFIX,oth.eve.mdt.qq.com,REJECT",
    "DOMAIN-SUFFIX,monitor.uu.qq.com,REJECT",
    "DOMAIN-SUFFIX,pgdt.gtimg.cn,REJECT",

    // 微信内部广告域名
    "DOMAIN-SUFFIX,ad.wechat.com,REJECT",
    "DOMAIN-KEYWORD,trace.qq.com,REJECT",


    // 酷壳
    "DOMAIN-SUFFIX,coolshell.cn,🐙 GitHub",


    // === GitHub 规则 (走 GitHub 组) ===
    
    "DOMAIN-KEYWORD,github,🐙 GitHub",
    "DOMAIN-SUFFIX,github.com,🐙 GitHub",
    "DOMAIN-SUFFIX,githubusercontent.com,🐙 GitHub",
    "DOMAIN-SUFFIX,githubassets.com,🐙 GitHub",
    "DOMAIN-SUFFIX,git.io,🐙 GitHub",
    "DOMAIN-KEYWORD,github,🐙 GitHub",

    "DOMAIN-SUFFIX,login.microsoft.com,🐙 GitHub",
    "DOMAIN-SUFFIX,microsoftonline.com,🐙 GitHub",
    
    // === AI 模型规则 (走 AI 模型组) ===
    // ChatGPT / OpenAI
    "DOMAIN-SUFFIX,chatgpt.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,openai.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,oaistatic.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,oaiusercontent.com,🤖 AI 模型",
    "DOMAIN-KEYWORD,openai,🤖 AI 模型",
    "DOMAIN-SUFFIX,identrust.com,🤖 AI 模型",
    
    // Claude / Anthropic
    "DOMAIN-SUFFIX,claude.ai,🤖 AI 模型",
    "DOMAIN-SUFFIX,anthropic.com,🤖 AI 模型",
    
    // Google Gemini / AI Studio
    "DOMAIN-SUFFIX,googleapis.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,alkalimakersuite-pa.clients6.google.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,makersuite.google.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,ai.google.dev,🤖 AI 模型",
    "DOMAIN-SUFFIX,ai.google.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,gemini.google.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,bard.google.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,aistudio.google.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,generativelanguage.googleapis.com,🤖 AI 模型",
    
    // Copilot (微软 AI)
    "DOMAIN-SUFFIX,copilot.microsoft.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,bing.com,🤖 AI 模型",
    "DOMAIN-SUFFIX,onenote.cloud.microsoft,🤖 AI 模型",
    "DOMAIN-SUFFIX,onedrive.live.com,🤖 AI 模型",

  ];

  // --- 4. 插入配置 ---

  // 将新组插入到列表最前面
  config['proxy-groups'].unshift(...newGroups);

  // 将新规则插入到列表最前面 (优先级最高)
  config['rules'].unshift(...newRules);

  return config;
}
