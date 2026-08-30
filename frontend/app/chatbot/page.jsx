
"use client"
import { useState, useEffect, useRef } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import Navbar from "../Navbar"
import { Poppins } from "next/font/google"
import {
  Send,
  Bot,
  User,
  Loader2,
  AlertCircle,
  Sparkles,
  MessageSquare,
  Brain,
  TrendingUp,
  Package,
  ShieldCheck,
  Copy,
  Check,
  RefreshCw,
} from "lucide-react"

const poppins = Poppins({ weight: ["400", "500", "600", "700"], subsets: ["latin"] })
const API_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:5000"

export default function Chatbot() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const [userId, setUserId] = useState(null)
  const [userRole, setUserRole] = useState(null)
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  // Authentication logic
  useEffect(() => {
    const userIdParam = searchParams.get("userId")
    const roleParam = searchParams.get("role")

    if (userIdParam && roleParam) {
      setUserId(parseInt(userIdParam))
      setUserRole(roleParam)
      setIsAuthenticated(true)
      localStorage.setItem("userid", userIdParam)
      localStorage.setItem("userrole", roleParam)
      localStorage.setItem("isAuthenticated", "true")
    } else {
      const storedUserId = localStorage.getItem("userid")
      const storedRole = localStorage.getItem("userrole")
      const storedAuth = localStorage.getItem("isAuthenticated")

      if (storedUserId && storedRole && storedAuth === "true") {
        setUserId(parseInt(storedUserId))
        setUserRole(storedRole)
        setIsAuthenticated(true)
      } else {
        setIsAuthenticated(false)
        setTimeout(() => router.push("/auth/login"), 2000)
      }
    }
  }, [searchParams, router])

  // Chat states
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: `Hello! I'm your AI compliance assistant. I can help you with:\n\n• **Personal Data Queries**: Ask about your products, compliance scores, and statistics\n• **General Compliance**: Learn about regulations, rules, and requirements\n\nHow can I help you today?`,
      intent: "greeting",
      timestamp: new Date().toISOString(),
    },
  ])
  const [inputMessage, setInputMessage] = useState("")
  const [loading, setLoading] = useState(false)
  const [copiedIndex, setCopiedIndex] = useState(null)

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Handle send message
  const handleSendMessage = async () => {
    if (!inputMessage.trim() || loading) return

    if (!isAuthenticated || !userId || !userRole) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Authentication required. Please log in to continue.",
          intent: "error",
          timestamp: new Date().toISOString(),
        },
      ])
      return
    }

    const userMessage = {
      role: "user",
      content: inputMessage.trim(),
      timestamp: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInputMessage("")
    setLoading(true)

    try {
      const response = await fetch(`${API_BASE_URL}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          message: inputMessage.trim(),
        }),
      })

      const data = await response.json()
     console.log(data)
      if (!response.ok) {
        if (response.status === 401) {
          localStorage.clear()
          setTimeout(() => router.push("/auth/login"), 1500)
          throw new Error("Session expired. Please log in again.")
        }
        throw new Error(data.error || "Failed to get response")
      }

      const assistantContent =
  typeof data.message === "string"
    ? data.message
    : Array.isArray(data.message)
      ? data.message
          .map((item) => {
            if (typeof item === "string") return item
            if (item?.text) return item.text
            return ""
          })
          .filter(Boolean)
          .join("")
      : data.message?.text || JSON.stringify(data.message)

const assistantMessage = {
  role: "assistant",
  content: assistantContent,
  intent: data.intent,
  user_context: data.user_context,
  timestamp: data.timestamp,
}

      setMessages((prev) => [...prev, assistantMessage])
    } catch (error) {
      console.error("Chat API error:", error)
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Error: ${error.message}`,
          intent: "error",
          timestamp: new Date().toISOString(),
        },
      ])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  // Handle Enter key
  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  // Copy message to clipboard
  const copyToClipboard = (text, index) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  // Clear chat
  const handleClearChat = () => {
    setMessages([
      {
        role: "assistant",
        content: `Hello! I'm your AI compliance assistant. I can help you with:\n\n• **Personal Data Queries**: Ask about your products, compliance scores, and statistics\n• **General Compliance**: Learn about regulations, rules, and requirements\n\nHow can I help you today?`,
        intent: "greeting",
        timestamp: new Date().toISOString(),
      },
    ])
  }

  // Format timestamp
  const formatTime = (timestamp) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  // Get intent icon and color
  const getIntentStyle = (intent) => {
    switch (intent) {
      case "personal_data":
        return { icon: Package, color: "text-cyan-400", bg: "bg-cyan-500/20", border: "border-cyan-400/50" }
      case "general_compliance":
        return { icon: ShieldCheck, color: "text-purple-400", bg: "bg-purple-500/20", border: "border-purple-400/50" }
      case "error":
        return { icon: AlertCircle, color: "text-red-400", bg: "bg-red-500/20", border: "border-red-400/50" }
      default:
        return { icon: Brain, color: "text-green-400", bg: "bg-green-500/20", border: "border-green-400/50" }
    }
  }

  // Show authentication warning if not authenticated
  if (!isAuthenticated) {
    return (
      <>
        <Navbar />
        <div className="min-h-screen bg-black text-white p-4 sm:p-6 md:p-8 ml-0 md:ml-64 flex items-center justify-center">
          <div className="bg-red-900/20 border border-red-500/30 rounded-2xl p-8 max-w-2xl">
            <div className="flex items-center gap-4 mb-4">
              <AlertCircle className="w-12 h-12 text-red-400" />
              <h2 className="text-2xl font-bold text-red-400">Authentication Required</h2>
            </div>
            <p className="text-gray-300 mb-4">Please log in to access the chatbot. Redirecting to login...</p>
            <button
              onClick={() => router.push("/auth/login")}
              className="px-6 py-3 bg-gradient-to-r from-purple-600 to-cyan-600 rounded-lg font-semibold hover:shadow-[0_0_30px_rgba(168,85,247,0.5)] transition-all"
            >
              Go to Login
            </button>
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      <Navbar />
      <div className="min-h-screen bg-black text-white p-4 sm:p-6 md:p-8 ml-0 md:ml-64">
        <div className="max-w-6xl mx-auto h-[calc(100vh-4rem)]">
          {/* Header */}
          <div className="mb-6 mt-6">
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold mb-2">
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-cyan-400 tracking-tight">
                AI Chatbot
              </span>
            </h2>
            <div className="border-t-2 border-image-[linear-gradient(to_right,theme(colors.purple.400),theme(colors.cyan.400))_1]"></div>
            <div className="flex items-center justify-between mt-2">
              <p className={`text-xs sm:text-sm ${poppins.className} tracking-wider uppercase text-gray-400`}>
                Intelligent compliance assistant with intent detection
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleClearChat}
                  className="px-3 py-1 bg-purple-600/20 border border-purple-500/30 rounded-lg hover:bg-purple-600/30 transition-all text-xs uppercase tracking-wider flex items-center gap-2"
                  aria-label="Clear chat"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span className="hidden sm:inline">Clear</span>
                </button>
                <div className={`text-xs ${poppins.className} text-cyan-400`}>
                  User: <span className="font-mono">{userId}</span> | Role:{" "}
                  <span className="font-semibold uppercase">{userRole}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Chat Container */}
          <div className="flex flex-col h-[calc(100%-10rem)] bg-black/60 border border-purple-500/30 rounded-2xl backdrop-blur-sm">
            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 scrollbar-thin scrollbar-thumb-purple-500/30 scrollbar-track-transparent">
              {messages.map((message, index) => {
                const isUser = message.role === "user"
                const intentStyle = !isUser ? getIntentStyle(message.intent) : null
                const IntentIcon = intentStyle?.icon

                return (
                  <div
                    key={index}
                    className={`flex gap-3 sm:gap-4 ${isUser ? "justify-end" : "justify-start"} animate-fade-in`}
                  >
                    {/* Assistant Avatar */}
                    {!isUser && (
                      <div className={`flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-full ${intentStyle.bg} border ${intentStyle.border} flex items-center justify-center`}>
                        {IntentIcon ? (
                          <IntentIcon className={`w-4 h-4 sm:w-5 sm:h-5 ${intentStyle.color}`} />
                        ) : (
                          <Bot className="w-4 h-4 sm:w-5 sm:h-5 text-purple-400" />
                        )}
                      </div>
                    )}

                    {/* Message Content */}
                    <div className={`flex flex-col max-w-[85%] sm:max-w-[75%] ${isUser ? "items-end" : "items-start"}`}>
                      <div
                        className={`rounded-2xl p-3 sm:p-4 ${
                          isUser
                            ? "bg-gradient-to-r from-purple-600 to-cyan-600 text-white"
                            : "bg-black/40 border border-purple-500/30 text-gray-200"
                        }`}
                      >
                        <div
                          className={`text-sm sm:text-base ${poppins.className} whitespace-pre-wrap break-words`}
                          dangerouslySetInnerHTML={{
                            __html: (
                              typeof message.content === "string"
                                ? message.content
                                : JSON.stringify(message.content, null, 2)
                            )
                              .replace(/\*\*(.*?)\*\*/g, '<strong class="font-bold text-white">$1</strong>')
                              .replace(/\n/g, "<br/>")
                              .replace(/•/g, '<span class="text-cyan-400">•</span>'),
                          }}
                        />

                        {/* User Context Display */}
                        {/* {message.user_context && (
                          <div className="mt-3 pt-3 border-t border-purple-500/30 space-y-2">
                            <div className="flex items-center gap-2 text-xs text-purple-400 uppercase tracking-wider">
                              <TrendingUp className="w-3 h-3" />
                              Your Stats
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-xs">
                              <div className="bg-black/40 border border-purple-500/20 rounded-lg p-2">
                                <p className="text-gray-400 uppercase text-[10px] tracking-wider">Total Products</p>
                                <p className="text-white font-bold">{message.user_context.stats.total_products}</p>
                              </div>
                              <div className="bg-black/40 border border-green-500/20 rounded-lg p-2">
                                <p className="text-gray-400 uppercase text-[10px] tracking-wider">Compliant</p>
                                <p className="text-green-400 font-bold">{message.user_context.stats.compliant_products}</p>
                              </div>
                              <div className="bg-black/40 border border-red-500/20 rounded-lg p-2">
                                <p className="text-gray-400 uppercase text-[10px] tracking-wider">Non-Compliant</p>
                                <p className="text-red-400 font-bold">{message.user_context.stats.non_compliant_products}</p>
                              </div>
                              <div className="bg-black/40 border border-cyan-500/20 rounded-lg p-2">
                                <p className="text-gray-400 uppercase text-[10px] tracking-wider">Avg Score</p>
                                <p className="text-cyan-400 font-bold">{message.user_context.stats.avg_compliance_score}</p>
                              </div>
                            </div>
                          </div>
                        )} */}
                      </div>

                      {/* Message Footer */}
                      <div className="flex items-center gap-2 mt-1 px-2">
                        <span className="text-[10px] text-gray-500 uppercase tracking-wider">
                          {formatTime(message.timestamp)}
                        </span>
                        {!isUser && (
                          <>
                            <span className="text-gray-600">•</span>
                            <button
                              onClick={() => copyToClipboard(message.content, index)}
                              className="text-gray-500 hover:text-cyan-400 transition-colors"
                              aria-label="Copy message"
                            >
                              {copiedIndex === index ? (
                                <Check className="w-3 h-3" />
                              ) : (
                                <Copy className="w-3 h-3" />
                              )}
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    {/* User Avatar */}
                    {isUser && (
                      <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-full bg-gradient-to-r from-purple-600 to-cyan-600 flex items-center justify-center">
                        <User className="w-4 h-4 sm:w-5 sm:h-5 text-white" />
                      </div>
                    )}
                  </div>
                )
              })}

              {/* Loading Indicator */}
              {loading && (
                <div className="flex gap-3 sm:gap-4 justify-start animate-fade-in">
                  <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-full bg-purple-500/20 border border-purple-400/50 flex items-center justify-center">
                    <Bot className="w-4 h-4 sm:w-5 sm:h-5 text-purple-400" />
                  </div>
                  <div className="bg-black/40 border border-purple-500/30 rounded-2xl p-3 sm:p-4">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
                      <span className={`text-sm ${poppins.className} text-gray-400 uppercase tracking-wider`}>
                        Analyzing...
                      </span>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="border-t border-purple-500/30 p-4 sm:p-6 bg-black/40">
              {/* Quick Suggestions */}
              <div className="flex flex-wrap gap-2 mb-3">
                <button
                  onClick={() => setInputMessage("Show me my products with low compliance scores")}
                  className="px-3 py-1 bg-purple-600/20 border border-purple-500/30 rounded-full text-xs uppercase tracking-wider hover:bg-purple-600/30 transition-all text-gray-300"
                  disabled={loading}
                >
                  My Products
                </button>
                <button
                  onClick={() => setInputMessage("What is the Legal Metrology Act?")}
                  className="px-3 py-1 bg-cyan-600/20 border border-cyan-500/30 rounded-full text-xs uppercase tracking-wider hover:bg-cyan-600/30 transition-all text-gray-300"
                  disabled={loading}
                >
                  Legal Metrology
                </button>
                <button
                  onClick={() => setInputMessage("What's my average compliance score?")}
                  className="px-3 py-1 bg-green-600/20 border border-green-500/30 rounded-full text-xs uppercase tracking-wider hover:bg-green-600/30 transition-all text-gray-300"
                  disabled={loading}
                >
                  My Stats
                </button>
              </div>

              {/* Input Field */}
              <div className="flex gap-2 sm:gap-3">
                <div className="flex-1 relative">
                  <textarea
                    ref={inputRef}
                    value={inputMessage}
                    onChange={(e) => setInputMessage(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Ask about your products or compliance regulations..."
                    className={`w-full px-4 py-3 bg-black/40 border border-purple-500/30 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:border-cyan-400/50 transition-all resize-none ${poppins.className} text-sm sm:text-base`}
                    rows="1"
                    disabled={loading}
                    style={{ minHeight: "48px", maxHeight: "120px" }}
                  />
                </div>
                <button
                  onClick={handleSendMessage}
                  disabled={loading || !inputMessage.trim()}
                  className="px-4 sm:px-6 py-3 bg-gradient-to-r from-purple-600 to-cyan-600 rounded-xl font-semibold hover:shadow-[0_0_30px_rgba(168,85,247,0.5)] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
                  aria-label="Send message"
                >
                  {loading ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Send className="w-5 h-5" />
                  )}
                </button>
              </div>

              {/* Helper Text */}
              <p className="text-[10px] text-gray-500 mt-2 text-center uppercase tracking-wider">
                Press Enter to send • Shift + Enter for new line
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Custom Animations */}
      <style jsx global>{`
        @keyframes fade-in {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .animate-fade-in {
          animation: fade-in 0.3s ease-out;
        }

        .scrollbar-thin::-webkit-scrollbar {
          width: 8px;
        }

        .scrollbar-thin::-webkit-scrollbar-track {
          background: transparent;
        }

        .scrollbar-thin::-webkit-scrollbar-thumb {
          background: linear-gradient(180deg, rgba(168, 85, 247, 0.3), rgba(6, 182, 212, 0.3));
          border-radius: 10px;
          transition: all 0.3s ease;
        }

        .scrollbar-thin::-webkit-scrollbar-thumb:hover {
          background: linear-gradient(180deg, rgba(168, 85, 247, 0.6), rgba(6, 182, 212, 0.6));
        }

        scrollbar-width: thin;
        scrollbar-color: rgba(168, 85, 247, 0.3) transparent;
      `}</style>
    </>
  )
}
