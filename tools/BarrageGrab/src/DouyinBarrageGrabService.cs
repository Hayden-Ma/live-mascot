using BarrageGrab.Entity.Enums;
using BarrageGrab.Entity.Models.Douyin;
using BarrageGrab.Framework;
using BarrageGrab.Entity.Protobuf.Douyin;
using Google.Protobuf;
using RestSharp;
using System;
using System.Collections.Generic;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;
using BarrageGrab.Framework.Utils;
using BarrageGrab.Entity.Models;
using Newtonsoft.Json;
using System.Collections.Concurrent;
using BarrageGrab.Framework.Helper;
using BarrageGrab.Entity.Requests;
using System.Text.Json.Nodes;
using static System.Windows.Forms.VisualStyles.VisualStyleElement.TaskBand;

namespace BarrageGrab.GrabServices
{
    /// <summary>
    /// Douyin barrage grab service
    /// </summary>
    internal class DouyinBarrageGrabService : IBarrageGrabService, IDisposable
    {
        #region Attributes & Fields

        /// <summary>
        /// User-Agent
        /// </summary>
        private string UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";


        /// <summary>
        /// liveid
        /// if live url is https://live.douyin.com/751990192217
        /// so 751990192217 is the liveid
        /// </summary>
        private string LiveId = string.Empty;

        private string? UserUniqueId { get; set; }


        /// <summary>
        /// 当前连接（Stop 时用来中断阻塞中的 ReceiveAsync）
        /// </summary>
        private ClientWebSocket? activeSocket;

        /// <summary>
        /// 重连循环的取消令牌
        /// </summary>
        private CancellationTokenSource? reconnectCts;

        /// <summary>
        /// 连续失败次数，收到数据后归零
        /// </summary>
        private int consecutiveFailures = 0;

        /// <summary>
        /// 接收超时（秒）：这么久没有收到任何数据就判定连接已静默断开
        /// </summary>
        private const int ReceiveTimeoutSeconds = 120;

        /// <summary>
        /// 连续失败多少次后强制重新获取签名地址
        /// </summary>
        private const int FailuresBeforeResign = 3;

        /// <summary>
        /// 最大重连间隔（秒）
        /// </summary>
        private const int MaxReconnectDelaySeconds = 30;



        #region Ttwid
        private string? _ttwid = string.Empty;
        private string? Ttwid
        {
            get
            {
                if (String.IsNullOrWhiteSpace(_ttwid))
                {
                    _ttwid = GetTtwid();
                }

                return _ttwid;
            }
            set
            {
                this._ttwid = value;
            }
        }
        #endregion


        #region RoomId
        private string? _roomid = string.Empty;
        private string? RoomId
        {
            get
            {
                if (String.IsNullOrWhiteSpace(_roomid))
                {
                    _roomid = GetRoomId();
                }

                return _roomid;
            }
            set
            {
                this._roomid = value;
            }
        }
        #endregion


        #region Wss
        private string _wss = string.Empty;
        private string Wss
        {
            get
            {
                if (String.IsNullOrWhiteSpace(_wss))
                {
                    _wss = GetWss();
                }

                return _wss;
            }
            set
            {
                this._wss = value;
            }
        }
        #endregion



        /// <summary>
        /// on open
        /// </summary>
        public event EventHandler? OnOpen;

        /// <summary>
        /// on message
        /// </summary>
        public event EventHandler? OnMessage;

        /// <summary>
        /// on error
        /// </summary>
        public event EventHandler? OnError;

        /// <summary>
        /// on close
        /// </summary>
        public event EventHandler? OnClose;


        #endregion










        public void Start(string liveId)
        {
            LiveId = liveId;

            lock (this)
            {
                // 取消可能存在的上一轮重连循环
                reconnectCts?.Cancel();
                reconnectCts?.Dispose();
                reconnectCts = new CancellationTokenSource();
                consecutiveFailures = 0;

                CancellationToken token = reconnectCts.Token;
                Task.Run(() => ReconnectLoopAsync(token), token);
            }
        }

        public void Stop()
        {
            lock (this)
            {
                try
                {
                    reconnectCts?.Cancel();
                }
                catch (Exception)
                {
                    // do something
                }

                reconnectCts?.Dispose();
                reconnectCts = null;
            }

            try
            {
                activeSocket?.Abort();
                activeSocket?.Dispose();
                activeSocket = null;
            }
            catch (Exception)
            {
                // do something
            }
        }

        public void ReStart()
        {
            this.Stop();

            this.Start(LiveId);
        }


        /// <summary>
        /// 断线重连主循环：连接 → 收消息 → 断线后指数退避重连；
        /// 连续多次失败后清空缓存的签名地址，强制重新签名
        /// </summary>
        private async Task ReconnectLoopAsync(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                ClientWebSocket? socket = null;
                System.Timers.Timer? heartbeatTimer = null;

                try
                {
                    socket = new ClientWebSocket();
                    socket.Options.SetRequestHeader("cookie", $"ttwid={Ttwid}");
                    socket.Options.SetRequestHeader("user-agent", UserAgent);
                    activeSocket = socket;

                    //connect
                    await socket.ConnectAsync(new Uri(Wss), token);

                    if (socket.State != WebSocketState.Open)
                    {
                        throw new Exception("连接服务器失败");
                    }

                    OnOpen?.Invoke(socket, EventArgs.Empty);
                    ApplicationRuntime.MainWindow?.PrintConsole("[连接]弹幕服务已连接");


                    #region 发送hb心跳
                    byte[] heartbeat = new byte[] { 0x3a, 0x02, 0x68, 0x62 };
                    await socket.SendAsync(new ArraySegment<byte>(heartbeat), WebSocketMessageType.Binary, true, token);

                    heartbeatTimer = new System.Timers.Timer(10000);
                    heartbeatTimer.Elapsed += (sender, e) =>
                    {
                        try
                        {
                            if (socket.State != WebSocketState.Open)
                            {
                                socket.Abort();
                                return;
                            }

                            socket.SendAsync(new ArraySegment<byte>(heartbeat), WebSocketMessageType.Binary, true, CancellationToken.None)
                                .ContinueWith(t =>
                                {
                                    if (t.IsFaulted || t.IsCanceled)
                                    {
                                        try { socket.Abort(); } catch (Exception) { }
                                    }
                                });
                        }
                        catch (Exception)
                        {
                            try { socket.Abort(); } catch (Exception) { }
                        }
                    };
                    heartbeatTimer.Start();
                    #endregion


                    //缓冲写大一些，就不用while循环分多次取
                    byte[] buffer = new byte[1024 * 10000];

                    while (!token.IsCancellationRequested)
                    {
                        WebSocketReceiveResult result;

                        // 给每次接收设置超时：长时间收不到任何数据说明连接已静默断开
                        using (CancellationTokenSource receiveCts = new CancellationTokenSource())
                        using (CancellationTokenSource linkedCts = CancellationTokenSource.CreateLinkedTokenSource(token, receiveCts.Token))
                        {
                            receiveCts.CancelAfter(TimeSpan.FromSeconds(ReceiveTimeoutSeconds));

                            try
                            {
                                result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), linkedCts.Token);
                            }
                            catch (OperationCanceledException) when (!token.IsCancellationRequested)
                            {
                                throw new TimeoutException($"{ReceiveTimeoutSeconds}秒未收到数据，判定连接已断开");
                            }
                        }

                        if (result.CloseStatus.HasValue)
                        {
                            throw new Exception($"服务端关闭连接：{result.CloseStatus}");
                        }

                        // 收到数据说明连接正常，失败计数归零
                        consecutiveFailures = 0;

                        #region 处理消息
                        //将接收到的数据写到缓冲里
                        var package = PushFrame.Parser.ParseFrom(new MemoryStream(buffer, 0, result.Count));
                        var response = Response.Parser.ParseFrom(DecompressHelper.Decompress(package.Payload.ToArray()));

                        #region if NeedAck
                        if (response.NeedAck)
                        {
                            PushFrame ack = new PushFrame()
                            {
                                LogId = package.LogId,
                                PayloadType = "ack",
                                Payload = ByteString.CopyFromUtf8(response.InternalExt)
                            };

                            await socket.SendAsync(new ArraySegment<byte>(ack.ToByteString().ToArray()), WebSocketMessageType.Binary, true, token);
                        }
                        #endregion

                        #region 处理消息数据（这里只是写个例子）
                        if (response.MessagesList != null && response.MessagesList.Count > 0)
                        {
                            foreach (var message in response.MessagesList)
                            {
                                switch (message.Method)
                                {
                                    #region WebcastMemberMessage 进入
                                    case "WebcastMemberMessage":
                                        {
                                            MemberMessage memberMsg = MemberMessage.Parser.ParseFrom(message.Payload);

                                            OpenBarrageMessage obm = new OpenBarrageMessage()
                                            {
                                                Type = MessageTypeEnum.Member,
                                                Data = new DouyinMsgMember()
                                                {
                                                    MsgId = (long)memberMsg.Common.MsgId,
                                                    Content = $"{memberMsg.User.NickName} 来了",
                                                    RoomId = (long)memberMsg.Common.RoomId,
                                                    MemberCount = (long)memberMsg.MemberCount,
                                                    User = GetUser(memberMsg.User)
                                                }
                                            };

                                            ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                            ApplicationRuntime.MainForm?.PrintConsole($"[进入]{memberMsg.User.NickName} 来了");

                                            break;
                                        }
                                    #endregion

                                    #region WebcastSocialMessage 关注 & 分享
                                    case "WebcastSocialMessage":
                                        {
                                            SocialMessage socialMessage = SocialMessage.Parser.ParseFrom(message.Payload);

                                            #region 分享
                                            if (socialMessage.Action == 3)
                                            {
                                                OpenBarrageMessage obm = new OpenBarrageMessage()
                                                {
                                                    Type = MessageTypeEnum.Share,
                                                    Data = new DouyinMsgShare()
                                                    {
                                                        MsgId = (long)socialMessage.Common.MsgId,
                                                        Content = $"{socialMessage.User.NickName} 分享了直播间到{socialMessage.ShareTarget}",
                                                        RoomId = (long)socialMessage.Common.RoomId,
                                                        //ShareType = socialMessage.ShareTarget,
                                                        User = GetUser(socialMessage.User)
                                                    }
                                                };

                                                ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                                ApplicationRuntime.MainForm?.PrintConsole($"[分享]{socialMessage.User.NickName} 分享了直播间到{socialMessage.ShareTarget}");
                                            }
                                            #endregion

                                            #region 关注
                                            else
                                            {
                                                OpenBarrageMessage obm = new OpenBarrageMessage()
                                                {
                                                    Type = MessageTypeEnum.Social,
                                                    Data = new DouyinMsgSocial()
                                                    {
                                                        MsgId = (long)socialMessage.Common.MsgId,
                                                        Content = $"{socialMessage.User.NickName} 关注了主播",
                                                        RoomId = (long)socialMessage.Common.RoomId,
                                                        User = GetUser(socialMessage.User)
                                                    }
                                                };

                                                ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                                ApplicationRuntime.MainForm?.PrintConsole($"[关注]{socialMessage.User.NickName} 关注了主播");
                                            }
                                            #endregion

                                            break;
                                        }
                                    #endregion

                                    #region WebcastChatMessage 弹幕
                                    case "WebcastChatMessage":
                                        {
                                            ChatMessage chatMessage = ChatMessage.Parser.ParseFrom(message.Payload);

                                            OpenBarrageMessage obm = new OpenBarrageMessage()
                                            {
                                                Type = MessageTypeEnum.Chat,
                                                Data = new DouyinMsgChat()
                                                {
                                                    MsgId = (long)chatMessage.Common.MsgId,
                                                    Content = chatMessage.Content,
                                                    RoomId = (long)chatMessage.Common.RoomId,
                                                    User = GetUser(chatMessage.User)
                                                }
                                            };

                                            ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                            ApplicationRuntime.MainForm?.PrintConsole($"[弹幕]{chatMessage.User.NickName} 说 {chatMessage.Content}");

                                            break;
                                        }
                                    #endregion

                                    #region WebcastLikeMessage 点赞
                                    case "WebcastLikeMessage":
                                        {
                                            LikeMessage likeMessage = LikeMessage.Parser.ParseFrom(message.Payload);

                                            OpenBarrageMessage obm = new OpenBarrageMessage()
                                            {
                                                Type = MessageTypeEnum.Like,
                                                Data = new DouyinMsgLike()
                                                {
                                                    MsgId = (long)likeMessage.Common.MsgId,
                                                    Count = (long)likeMessage.Count,
                                                    Total = (long)likeMessage.Total,
                                                    Content = $"{likeMessage.User.NickName} 为主播点了{likeMessage.Count.ToString()}个赞，总点赞{likeMessage.Total.ToString()}",
                                                    RoomId = (long)likeMessage.Common.RoomId,
                                                    User = GetUser(likeMessage.User)
                                                }
                                            };

                                            ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                            ApplicationRuntime.MainForm?.PrintConsole($"[点赞]{likeMessage.User.NickName} 点了 {likeMessage.Count.ToString()} 个赞");

                                            break;
                                        }
                                    #endregion

                                    #region WebcastGiftMessage 礼物
                                    case "WebcastGiftMessage":
                                        {
                                            GiftMessage giftMessage = GiftMessage.Parser.ParseFrom(message.Payload);

                                            OpenBarrageMessage obm = new OpenBarrageMessage()
                                            {
                                                Type = MessageTypeEnum.Gift,
                                                Data = new DouyinMsgGift()
                                                {
                                                    MsgId = (long)giftMessage.Common.MsgId,
                                                    GiftId = (long)giftMessage.GiftId,
                                                    GiftName = giftMessage.Gift.Name,
                                                    TotalCount = (long)giftMessage.TotalCount,
                                                    RepeatCount = (long)giftMessage.RepeatCount,
                                                    RepeatEnd = (int)giftMessage.RepeatEnd,
                                                    ComboCount = (long)giftMessage.ComboCount,
                                                    GroupCount = (long)giftMessage.GroupCount,
                                                    DiamondCount = (int)giftMessage.Gift.DiamondCount,
                                                    Content = $"{giftMessage.User.NickName} 送出 {giftMessage.Gift.Name}{(giftMessage.Gift.Combo ? "(可连击)" : "")} x {giftMessage.RepeatCount}个", //，增量{count}个
                                                    RoomId = (long)giftMessage.Common.RoomId,
                                                    User = GetUser(giftMessage.User),
                                                    ToUser = GetUser(giftMessage.ToUser)
                                                }
                                            };

                                            ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                            ApplicationRuntime.MainForm?.PrintConsole($"[礼物]{giftMessage.User.NickName} 送出 {giftMessage.RepeatCount.ToString()} 个 {giftMessage.Gift.Name}");

                                            break;
                                        }
                                    #endregion

                                    #region WebcastRoomUserSeqMessage 统计
                                    case "WebcastRoomUserSeqMessage":
                                        {
                                            RoomUserSeqMessage roomUserSeqMessage = RoomUserSeqMessage.Parser.ParseFrom(message.Payload);

                                            OpenBarrageMessage obm = new OpenBarrageMessage()
                                            {
                                                Type = MessageTypeEnum.RoomUserSeq,
                                                Data = new DouyinMsgRoomUserSeq()
                                                {
                                                    MsgId = (long)roomUserSeqMessage.Common.MsgId,
                                                    OnlineUserCount = roomUserSeqMessage.Total,
                                                    TotalUserCount = roomUserSeqMessage.TotalUser,
                                                    TotalUserCountStr = roomUserSeqMessage.TotalPvForAnchor,
                                                    OnlineUserCountStr = roomUserSeqMessage.OnlineUserForAnchor,
                                                    Content = $"当前直播间人数 {roomUserSeqMessage.OnlineUserForAnchor}，累计直播间人数 {roomUserSeqMessage.TotalPvForAnchor}",
                                                    RoomId = (long)roomUserSeqMessage.Common.RoomId,
                                                    User = null
                                                }
                                            };

                                            ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                            ApplicationRuntime.MainForm?.PrintConsole($"[人气统计]当前直播间人数 {roomUserSeqMessage.OnlineUserForAnchor}，累计直播间人数 {roomUserSeqMessage.TotalPvForAnchor}");

                                            break;
                                        }
                                    #endregion

                                    #region WebcastControlMessage 直播间状态变更
                                    case "WebcastControlMessage":
                                        {
                                            ControlMessage controlMessage = ControlMessage.Parser.ParseFrom(message.Payload);

                                            OpenBarrageMessage obm = new OpenBarrageMessage()
                                            {
                                                Type = MessageTypeEnum.Control,
                                                Data = new DouyinMsgControl()
                                                {
                                                    MsgId = (long)controlMessage.Common.MsgId,
                                                    Content = controlMessage.Status == 3 ? "直播已结束" : "",
                                                    RoomId = (long)controlMessage.Common.RoomId,
                                                    User = null
                                                }
                                            };

                                            ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                            ApplicationRuntime.MainForm?.PrintConsole($"[系统]当前直播已结束");

                                            break;
                                        }
                                    #endregion

                                    #region WebcastFansclubMessage 粉丝团
                                    case "WebcastFansclubMessage":
                                        {
                                            FansclubMessage fansclubMessage = FansclubMessage.Parser.ParseFrom(message.Payload);

                                            DouyinMsgFansClub douyinMsgFansClub = new DouyinMsgFansClub()
                                            {
                                                MsgId = (long)fansclubMessage.CommonInfo.MsgId,
                                                Type = fansclubMessage.Type,
                                                Content = fansclubMessage.Content,
                                                RoomId = (long)fansclubMessage.CommonInfo.RoomId,
                                                User = GetUser(fansclubMessage.User)
                                            };

                                            if (douyinMsgFansClub.User != null && douyinMsgFansClub.User.FansClub != null)
                                            {
                                                douyinMsgFansClub.Level = douyinMsgFansClub.User.FansClub.Level;
                                            }

                                            OpenBarrageMessage obm = new OpenBarrageMessage()
                                            {
                                                Type = MessageTypeEnum.Fansclub,
                                                Data = douyinMsgFansClub
                                            };

                                            ApplicationRuntime.LocalWebSocketServer?.Broadcast(JsonConvert.SerializeObject(obm));

                                            ApplicationRuntime.MainForm?.PrintConsole($"[粉丝团]{fansclubMessage.User.NickName} 加入了主播粉丝团");

                                            break;
                                        }
                                    #endregion

                                    default:
                                        break;
                                }
                            }
                        }
                        #endregion

                        #endregion
                    }
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested)
                {
                    break;
                }
                catch (Exception ex)
                {
                    if (token.IsCancellationRequested)
                    {
                        break;
                    }

                    consecutiveFailures++;
                    OnError?.Invoke(socket, EventArgs.Empty);
                    ApplicationRuntime.MainWindow?.PrintConsole($"[断线]{ex.Message}");

                    if (consecutiveFailures >= FailuresBeforeResign)
                    {
                        //缓存的签名地址可能已过期，清空后强制重新走签名接口
                        _wss = string.Empty;
                        _roomid = string.Empty;
                        _ttwid = string.Empty;
                        ApplicationRuntime.MainWindow?.PrintConsole("[重连]连续失败多次，重新获取签名地址");
                    }

                    //指数退避：2、4、8、16、30 秒
                    int delay = Math.Min(MaxReconnectDelaySeconds, (int)Math.Pow(2, Math.Min(consecutiveFailures, 5)));
                    ApplicationRuntime.MainWindow?.PrintConsole($"[重连]{delay}秒后重连（连续失败 {consecutiveFailures} 次）");

                    try
                    {
                        await Task.Delay(TimeSpan.FromSeconds(delay), token);
                    }
                    catch (OperationCanceledException)
                    {
                        break;
                    }
                }
                finally
                {
                    if (heartbeatTimer != null)
                    {
                        try { heartbeatTimer.Stop(); } catch (Exception) { }
                        try { heartbeatTimer.Dispose(); } catch (Exception) { }
                    }

                    if (activeSocket == socket)
                    {
                        activeSocket = null;
                    }

                    try { socket?.Abort(); } catch (Exception) { }
                    try { socket?.Dispose(); } catch (Exception) { }
                }
            }
        }






        #region 方法





        #region GenerateMsToken
        static Random random = new Random();
        private string GenerateMsToken(int length = 107)
        {
            string baseStr = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789=_";

            StringBuilder str = new StringBuilder();

            int len = baseStr.Length;
            for (int i = 0; i < length; i++)
            {
                str.Append(baseStr[random.Next(0, len)]);
            }

            return str.ToString();
        }
        #endregion


        #region private string? GetTwid()
        private string? GetTtwid()
        {
            try
            {
                int defailedCount = 0;
                string? temp_ttwid = string.Empty;

                while (true)
                {
                    try
                    {
                        using (RestClient client = new RestClient(GlobalConfigs.LiveUrl_Douyin))
                        {
                            RestRequest request = new RestRequest($"/{LiveId}", Method.Get);
                            request.AddHeader("User-Agent", UserAgent);
                            request.AddCookie("__ac_nonce", "0" + GenerateMsToken(20), "/", "live.douyin.com"); //__ac_nonce 可以是任意值

                            RestResponse response = client.Execute(request);
                            if (response.StatusCode == HttpStatusCode.OK)
                            {
                                if (response.Cookies != null && response.Cookies.Count > 0)
                                {
                                    temp_ttwid = response.Cookies.Where(cookie => "ttwid".Equals(cookie.Name)).FirstOrDefault()?.Value;
                                }
                            }
                        }

                        if (!string.IsNullOrWhiteSpace(temp_ttwid))
                        {
                            break;
                        }
                        else
                        {
                            throw new Exception("空值，再来一次");
                        }
                    }
                    catch (Exception)
                    {
                        defailedCount++;
                        temp_ttwid = null;
                    }

                    //实在带不动了，算了
                    if (defailedCount > 5)
                    {
                        break;
                    }
                }

                return temp_ttwid;
            }
            catch (Exception)
            {
                return null;
            }
        }
        #endregion


        #region private string? GetRoomId()
        private string? GetRoomId()
        {
            try
            {
                using (RestClient client = new RestClient(GlobalConfigs.LiveUrl_Douyin))
                {
                    RestRequest request = new RestRequest($"/{LiveId}", Method.Get);

                    request.AddHeader("User-Agent", UserAgent);
                    request.AddHeader("cookie", $"ttwid={Ttwid}&msToken={GenerateMsToken()}; __ac_nonce=0{GenerateMsToken(20)}");

                    RestResponse response = client.Execute(request);
                    if (response.StatusCode == HttpStatusCode.OK)
                    {
                        //提取UserUniqueId
                        string id = string.Empty;
                        var reg_id = new Regex(@"user_unique_id\\"":\\""(?<userUniqueId>\d+)\\""", RegexOptions.IgnoreCase);
                        Match _match_id = reg_id.Match(response.Content ?? "");
                        if (_match_id.Success)
                        {
                            this.UserUniqueId = _match_id.Groups[1].Value;
                        }

                        //正则表达式，提取roomid
                        var reg = new Regex(@"roomId\\"":\\""(?<roomId>\d+)\\""", RegexOptions.IgnoreCase);
                        Match _match = reg.Match(response.Content ?? "");
                        if (_match.Success)
                        {
                            return _match.Groups["roomId"].Value;
                        }
                    }
                }

                return null;
            }
            catch (Exception)
            {
                return null;
            }
        }
        #endregion


        #region private string? GetWss()
        /// <summary>
        /// GetWss 通过部署的签名api获取签名后的wss地址
        /// 如需本地部署签名服务，请联系博主
        /// </summary>
        /// <returns></returns>
        private string? GetWss()
        {
            using (RestClient client = new RestClient(GlobalConfigs.SignApi_Domain))
            {
                RestRequest request = new RestRequest($"{GlobalConfigs.SignApi_Url}", Method.Post);
                request.AddHeader("Accept", "*/*");
                request.AddHeader("Accept-Encoding", "gzip, deflate, br, zstd");
                request.AddHeader("Accept-Language", "zh-CN,zh;q=0.9");
                request.AddHeader("Connection", "keep-alive");
                request.AddHeader("Content-Type", "application/json;charset=UTF-8");

                string body = JsonConvert.SerializeObject(new SignWssRequest()
                {
                    //临时apikey，如需申请独立apikey，请联系博主
                    //临时apikey仅供测试使用，请勿用于生产环境，恶意请求将自动永久封禁ip
                    ApiKey = GlobalConfigs.SignApi_Key,

                    //根据实际情况填写
                    BrowserName = "Mozilla",
                    //根据实际情况填写
                    BrowserVersion = UserAgent,

                    RoomId = RoomId,
                    UserUniqueId = UserUniqueId
                });

                request.AddHeader("Content-Length", Encoding.UTF8.GetByteCount(body));
                request.AddBody(body);


                RestResponse response = client.Execute(request);
                if (response != null)
                {
                    JsonNode? json = JsonNode.Parse(response.Content ?? "");

                    if (json == null) return null;

                    if (json["Code"] == null) return null;

                    if (json["Code"]!.GetValue<int>() != 0)
                    {
                        throw new Exception(json["Msg"]!.GetValue<string>());
                    }

                    if (json["Data"] == null) return null;

                    return json["Data"]!["WssUrl"]!.GetValue<string>();
                }
            }

            return null;
        }

        public void Dispose()
        {

        }

        #endregion


        #region private DouyinUser? GetUser(User data)
        private DouyinUser? GetUser(User data)
        {
            if (data == null)
            {
                return null;
            }

            DouyinUser user = new DouyinUser()
            {
                DisplayId = data.DisplayId,
                ShortId = (long)data.ShortId,
                Gender = (int)data.Gender,
                Id = (long)data.Id,
                Level = (int)data.Level,
                PayLevel = (int)(data.PayGrade?.Level ?? -1),
                NickName = data.NickName ?? "用户" + data.DisplayId,
                Avatar = data.AvatarThumb?.UrlListList?.FirstOrDefault() ?? "",
                SecUid = data.SecUid,
                FollowerCount = (long)(data.FollowInfo?.FollowerCount ?? 0),
                FollowingCount = (long)(data.FollowInfo?.FollowingCount ?? 0),
                FollowStatus = (long)(data.FollowInfo?.FollowStatus ?? 0)
            };

            if (data.FansClub != null && data.FansClub.Data != null)
            {
                user.FansClub = new DouyinFansClub()
                {
                    ClubName = data.FansClub.Data.ClubName,
                    Level = data.FansClub.Data.Level
                };
            }

            return user;
        }
        #endregion


        #endregion
    }
}
