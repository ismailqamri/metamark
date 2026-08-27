"use client";
import { useState, useRef, useEffect } from 'react';
import {
  Upload, Loader2, Camera, X, Send, AlertCircle, CheckCircle2,
  XCircle, ChevronDown, ChevronUp, Trash2, Shield, TrendingUp,
  Star, AlertTriangle, Info, Eye, Package, Plus, Video, Image as ImageIcon,
  ShoppingCart, Menu, Search, Bell, User, Home, Package2, FileText,
  Settings, LogOut, MapPin, DollarSign, BarChart3, MessageSquare,
  Weight, Ruler, Tag, Users, Map, Zap, ExternalLink, Filter, ChevronLeft,
  ChevronRight, Wifi, WifiOff, Activity
} from 'lucide-react';
import Navbar from '../Navbar';

const API_BASE_URL = 'http://localhost:5000';


const CATEGORIES = [
  { value: 'amazon', label: 'General (Amazon)' },
  { value: 'food', label: 'Food & Beverages' },
  { value: 'skincare', label: 'Skincare & Cosmetics' },
  { value: 'electric', label: 'Electronics & Electricals' },
  { value: 'book', label: 'Books & Stationery' },
];



export default function SellerVerification() {
  const [category, setCategory] = useState('amazon');
  const [description, setDescription] = useState('');
  const [actualWeight, setActualWeight] = useState('');
  const [actualDimensions, setActualDimensions] = useState('');
  const [images, setImages] = useState([]);
  const [imagePreviews, setImagePreviews] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState('');
  const [validationResult, setValidationResult] = useState(null);
  const [error, setError] = useState(null);
  const [expandedSections, setExpandedSections] = useState({});
  
  const [showWebcam, setShowWebcam] = useState(false);
  const [cameraStream, setCameraStream] = useState(null);
  const [cameraError, setCameraError] = useState(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  
  
  
  
  
  
  const startWebcam = async () => {
    try {
      setCameraError(null);
      const stream = await navigator.mediaDevices.getUserMedia({ 
        video: { 
          facingMode: 'environment',
          width: { ideal: 1280 },
          height: { ideal: 720 }
        } 
      });
      
      setCameraStream(stream);
      setShowWebcam(true);
      
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(err => {
            console.error('Error playing video:', err);
            setCameraError('Failed to start video playback');
          });
        }
      }, 100);
      
      setError(null);
    } catch (err) {
      console.error('Camera error:', err);
      setCameraError('Failed to access camera. Please check permissions.');
      setError('Failed to access camera: ' + err.message);
      setShowWebcam(false);
    }
  };

  const stopWebcam = () => {
    if (cameraStream) {
      cameraStream.getTracks().forEach(track => track.stop());
      setCameraStream(null);
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setShowWebcam(false);
    setCameraError(null);
  };

  const capturePhoto = () => {
    if (videoRef.current && canvasRef.current && videoRef.current.readyState === videoRef.current.HAVE_ENOUGH_DATA) {
      const canvas = canvasRef.current;
      const video = videoRef.current;
      
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      
      canvas.toBlob((blob) => {
        if (blob) {
          const file = new File([blob], `webcam-${Date.now()}.jpg`, { type: 'image/jpeg' });
          setImages(prev => [...prev, file]);
          
          const reader = new FileReader();
          reader.onloadend = () => setImagePreviews(prev => [...prev, reader.result]);
          reader.readAsDataURL(file);
          
          setError(null);
        }
      }, 'image/jpeg', 0.95);
    } else {
      setError('Camera feed not ready. Please wait a moment and try again.');
    }
  };

  useEffect(() => {
    return () => {
      if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
      }
    };
  }, [cameraStream]);

  const handleImageUpload = (e) => {
    const files = Array.from(e.target.files);
    const validFiles = files.filter(file => 
      file.type === 'image/jpeg' || file.type === 'image/png'
    ).slice(0, 10 - images.length);
    
    setImages(prev => [...prev, ...validFiles]);
    validFiles.forEach((file) => {
      const reader = new FileReader();
      reader.onloadend = () => setImagePreviews(prev => [...prev, reader.result]);
      reader.readAsDataURL(file);
    });
  };

  const removeImage = (index) => {
    setImages(prev => prev.filter((_, i) => i !== index));
    setImagePreviews(prev => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (images.length < 1) {
      setError('Please upload or capture at least 1 product image');
      return;
    }

    if (!description.trim()) {
      setError('Please provide a product description');
      return;
    }

    setLoading(true);
    setValidationResult(null);
    setLoadingStage('Uploading product data...');

    try {
      const formData = new FormData();
      formData.append('category', category);
      formData.append('description', description.trim());
      formData.append('actual_weight', actualWeight.trim());
      formData.append('actual_dimensions', actualDimensions.trim());
      
      images.forEach((image) => formData.append('images', image));

      const stages = [
        'Uploading images...',
        'Running OCR analysis...',
        'AI validation in progress...',
        'Checking compliance...',
        'Generating report...'
      ];
      let idx = 0;
      const interval = setInterval(() => {
        if (idx < stages.length) setLoadingStage(stages[idx++]);
      }, 1800);

      const response = await fetch(`${API_BASE_URL}/api/seller/check-upload-text`, {
        method: 'POST',
        body: formData,
      });

      clearInterval(interval);
      const data = await response.json();

      if (!response.ok) throw new Error(data.error || 'Validation failed');

      setValidationResult(data.feedback);
      setLoadingStage('');
    } catch (err) {
      setError(err.message || 'Validation failed');
      setLoadingStage('');
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setValidationResult(null);
    setImages([]);
    setImagePreviews([]);
    setDescription('');
    setActualWeight('');
    setActualDimensions('');
    setCategory('amazon');
    setExpandedSections({});
    setError(null);
    setDimensionData({ length: 0, width: 0, height: 0 });
    stopWebcam();
  };

  const getGradeColor = (grade) => {
    if (!grade) return 'text-gray-400';
    const g = grade.toUpperCase();
    if (g.includes('A')) return 'text-green-400';
    if (g.includes('B')) return 'text-blue-400';
    if (g.includes('C')) return 'text-amber-400';
    return 'text-red-400';
  };

  const getGradeBg = (grade) => {
    if (!grade) return 'bg-gray-900/40 border-gray-500/30';
    const g = grade.toUpperCase();
    if (g.includes('A')) return 'bg-green-900/40 border-green-500/50';
    if (g.includes('B')) return 'bg-blue-900/40 border-blue-500/50';
    if (g.includes('C')) return 'bg-amber-900/40 border-amber-500/50';
    return 'bg-red-900/40 border-red-500/50';
  };

  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const renderIssues = (issues, severity, color, icon) => {
    if (!issues || issues.length === 0) return null;

    const colorClasses = {
      high: { bg: 'bg-red-900/20', border: 'border-red-500/30', text: 'text-red-400', hover: 'hover:border-red-400/50' },
      medium: { bg: 'bg-amber-900/20', border: 'border-amber-500/30', text: 'text-amber-400', hover: 'hover:border-amber-400/50' },
      low: { bg: 'bg-blue-900/20', border: 'border-blue-500/30', text: 'text-blue-400', hover: 'hover:border-blue-400/50' }
    };

    const classes = colorClasses[severity] || colorClasses.low;

    return (
      <div className={`${classes.bg} border ${classes.border} rounded-xl p-6 ${classes.hover} transition-all`}>
        <div className="flex items-center justify-between mb-4 cursor-pointer" onClick={() => toggleSection(severity)}>
          <div className="flex items-center gap-3">
            <div className={`p-2 ${classes.bg} rounded-lg border ${classes.border}`}>{icon}</div>
            <h4 className={`text-lg font-bold ${classes.text} uppercase tracking-wider`}>
              {severity.charAt(0).toUpperCase() + severity.slice(1)} Issues ({issues.length})
            </h4>
          </div>
          {expandedSections[severity] ? <ChevronUp className={`w-5 h-5 ${classes.text}`} /> : <ChevronDown className={`w-5 h-5 ${classes.text}`} />}
        </div>
        {expandedSections[severity] && (
          <div className="space-y-3 mt-4">
            {issues.map((issue, i) => (
              <div key={i} className={`bg-black/60 border ${classes.border} rounded-lg p-4 hover:bg-black/80 transition-all`}>
                <div className="flex items-start gap-3">
                  <div className={`p-2 ${classes.bg} rounded-lg`}>{icon}</div>
                  <div className="flex-1">
                    <div className={`font-semibold ${classes.text} mb-1 uppercase tracking-wide`}>
                      {issue.requirement || 'Requirement'}
                    </div>
                    <div className="text-sm text-gray-300 leading-relaxed">{issue.description || 'No description'}</div>
                    {issue.notes && <div className="text-xs text-gray-400 mt-2 italic">Note: {issue.notes}</div>}
                    {issue.penalty && <div className={`text-xs ${classes.text} mt-2 font-semibold`}>Penalty: {issue.penalty} points</div>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-black text-white">
      <Navbar />
      
      <div className="p-4 sm:p-8 pt-20">
        <div className="max-w-7xl mx-auto">
          <div className="mb-8">
            <div className="w-full">
              <h1 className="text-4xl md:text-5xl font-bold mb-2">
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-cyan-400 tracking-tight">
                  Product Compliance Verification
                </span>
              </h1>
              <div className="border-t-2 border-purple-400/50">
                <p className="mt-2 text-xs uppercase tracking-wider text-gray-400">
                  AI-powered validation with hardware integration
                </p>
              </div>
            </div>
          </div>

          <div className={`mb-6 p-4 rounded-xl border-2 flex items-center justify-between ${
            esp32Connected ? 'bg-green-900/20 border-green-500/50' : 'bg-red-900/20 border-red-500/50'
          }`}>
            <div className="flex items-center gap-3">
              {esp32Connected ? <Wifi className="w-6 h-6 text-green-400" /> : <WifiOff className="w-6 h-6 text-red-400" />}
              <div>
                <div className="font-semibold">Hardware Status: {esp32Status}</div>
                <div className="text-xs text-gray-400">ESP32 Gateway: {ESP32_GATEWAY_IP}</div>
              </div>
            </div>
            <button onClick={checkESP32Connection} className="px-4 py-2 bg-white/10 rounded-lg hover:bg-white/20 transition-all text-sm">
              Refresh
            </button>
          </div>

          {!validationResult ? (
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-6">
                  <div className="bg-gradient-to-br from-cyan-900/20 to-blue-900/20 border-2 border-cyan-500/50 rounded-xl p-6">
                    <div className="flex items-center gap-3 mb-6">
                      <Activity className="w-6 h-6 text-cyan-400" />
                      <h3 className="text-xl font-bold text-white uppercase tracking-wide">Hardware Measurements</h3>
                    </div>

                    {hardwareError && (
                      <div className="mb-4 flex items-center gap-3 text-amber-400 bg-amber-900/20 border border-amber-500/30 rounded-lg p-3 text-sm">
                        <AlertCircle className="w-5 h-5 flex-shrink-0" />
                        <span>{hardwareError}</span>
                      </div>
                    )}

                    <div className="mb-6 bg-black/40 rounded-lg p-4 border border-cyan-500/30">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <Weight className="w-5 h-5 text-cyan-400" />
                          <span className="font-semibold text-cyan-300">Weight Measurement</span>
                        </div>
                        <button
                          type="button"
                          onClick={getWeightFromHardware}
                          disabled={!esp32Connected || hardwareLoading}
                          className="px-4 py-2 bg-cyan-500/20 border border-cyan-500/50 rounded-lg text-cyan-300 hover:bg-cyan-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 text-sm font-semibold"
                        >
                          {hardwareLoading ? (
                            <>
                              <Loader2 className="w-4 h-4 animate-spin" />
                              Reading...
                            </>
                          ) : (
                            <>
                              <Weight className="w-4 h-4" />
                              Get Weight
                            </>
                          )}
                        </button>
                      </div>
                      {actualWeight && (
                        <div className="text-2xl font-bold text-cyan-400 text-center">{actualWeight}</div>
                      )}
                    </div>

                    <div className="bg-black/40 rounded-lg p-4 border border-cyan-500/30 mb-4">
                      <div className="flex items-center gap-2 mb-4">
                        <Ruler className="w-5 h-5 text-cyan-400" />
                        <span className="font-semibold text-cyan-300">Dimension Measurements</span>
                      </div>

                      <div className="grid grid-cols-3 gap-3 mb-4">
                        <button
                          type="button"
                          onClick={() => measureDimension('LENGTH')}
                          disabled={!esp32Connected || hardwareLoading}
                          className={`px-3 py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                            measurementMode === 'LENGTH' && hardwareLoading
                              ? 'bg-cyan-500/40 border-2 border-cyan-400'
                              : 'bg-cyan-500/20 border border-cyan-500/50 hover:bg-cyan-500/30'
                          }`}
                        >
                          {measurementMode === 'LENGTH' && hardwareLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                          ) : (
                            'Length'
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => measureDimension('WIDTH')}
                          disabled={!esp32Connected || hardwareLoading}
                          className={`px-3 py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                            measurementMode === 'WIDTH' && hardwareLoading
                              ? 'bg-cyan-500/40 border-2 border-cyan-400'
                              : 'bg-cyan-500/20 border border-cyan-500/50 hover:bg-cyan-500/30'
                          }`}
                        >
                          {measurementMode === 'WIDTH' && hardwareLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                          ) : (
                            'Width'
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => measureDimension('HEIGHT')}
                          disabled={!esp32Connected || hardwareLoading}
                          className={`px-3 py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                            measurementMode === 'HEIGHT' && hardwareLoading
                              ? 'bg-cyan-500/40 border-2 border-cyan-400'
                              : 'bg-cyan-500/20 border border-cyan-500/50 hover:bg-cyan-500/30'
                          }`}
                        >
                          {measurementMode === 'HEIGHT' && hardwareLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                          ) : (
                            'Height'
                          )}
                        </button>
                      </div>

                      {(dimensionData.length > 0 || dimensionData.width > 0 || dimensionData.height > 0) && (
                        <div className="grid grid-cols-3 gap-3 text-center mb-3">
                          <div>
                            <div className="text-xs text-gray-400">Length</div>
                            <div className="text-lg font-bold text-cyan-400">{(dimensionData.length / 10).toFixed(1)}cm</div>
                          </div>
                          <div>
                            <div className="text-xs text-gray-400">Width</div>
                            <div className="text-lg font-bold text-cyan-400">{(dimensionData.width / 10).toFixed(1)}cm</div>
                          </div>
                          <div>
                            <div className="text-xs text-gray-400">Height</div>
                            <div className="text-lg font-bold text-cyan-400">{(dimensionData.height / 10).toFixed(1)}cm</div>
                          </div>
                        </div>
                      )}

                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={getAllMeasurements}
                          disabled={!esp32Connected || hardwareLoading}
                          className="flex-1 px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 rounded-lg text-white font-semibold hover:shadow-lg hover:shadow-cyan-500/50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-all"
                        >
                          {hardwareLoading ? (
                            <>
                              <Loader2 className="w-4 h-4 animate-spin" />
                              Measuring...
                            </>
                          ) : (
                            <>
                              <Zap className="w-4 h-4" />
                              Get All
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={recalibrateSensor}
                          disabled={!esp32Connected || hardwareLoading}
                          className="px-4 py-2 bg-amber-500/20 border border-amber-500/50 rounded-lg text-amber-300 hover:bg-amber-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold"
                        >
                          Recalibrate
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="bg-black/60 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                    <label className="flex items-center gap-2 text-sm font-semibold text-purple-300 mb-3 uppercase tracking-wide">
                      <Package className="w-4 h-4" />
                      Product Category *
                    </label>
                    <select
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                      className="w-full px-4 py-3 bg-black/60 border border-purple-500/30 rounded-lg text-white focus:border-cyan-400/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20 transition-all"
                    >
                      {CATEGORIES.map(cat => (
                        <option key={cat.value} value={cat.value}>{cat.label}</option>
                      ))}
                    </select>
                  </div>

                  <div className="bg-black/60 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                    <label className="flex items-center gap-2 text-sm font-semibold text-purple-300 mb-3 uppercase tracking-wide">
                      <FileText className="w-4 h-4" />
                      Product Description *
                    </label>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      required
                      rows={6}
                      className="w-full px-4 py-3 bg-black/60 border border-purple-500/30 rounded-lg text-white resize-none focus:border-cyan-400/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20 transition-all"
                      placeholder="Describe your product in detail... Include brand, features, materials, usage instructions, etc."
                    />
                    <div className="flex items-center justify-between mt-2">
                      <div className="text-xs text-gray-400">Characters: {description.length}</div>
                      <div className="text-xs text-gray-500">Recommended: 100+ characters</div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="bg-black/60 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                      <label className="flex items-center gap-2 text-sm font-semibold text-purple-300 mb-3 uppercase tracking-wide">
                        <Weight className="w-4 h-4" />
                        Actual Weight
                      </label>
                      <input
                        type="text"
                        value={actualWeight}
                        onChange={(e) => setActualWeight(e.target.value)}
                        className="w-full px-4 py-3 bg-black/60 border border-purple-500/30 rounded-lg text-white focus:border-cyan-400/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20 transition-all"
                        placeholder="e.g., 250g, 1.5kg"
                      />
                    </div>

                    <div className="bg-black/60 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                      <label className="flex items-center gap-2 text-sm font-semibold text-purple-300 mb-3 uppercase tracking-wide">
                        <Ruler className="w-4 h-4" />
                        Actual Dimensions
                      </label>
                      <input
                        type="text"
                        value={actualDimensions}
                        onChange={(e) => setActualDimensions(e.target.value)}
                        className="w-full px-4 py-3 bg-black/60 border border-purple-500/30 rounded-lg text-white focus:border-cyan-400/50 focus:outline-none focus:ring-2 focus:ring-purple-500/20 transition-all"
                        placeholder="e.g., 15x10x5 cm"
                      />
                    </div>
                  </div>

                  <div className="bg-black/60 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="flex items-center gap-2 text-lg font-bold text-white">
                        <ImageIcon className="w-5 h-5 text-purple-400" />
                        Product Images * ({images.length}/10)
                      </h3>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={showWebcam ? stopWebcam : startWebcam}
                          className={`px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all ${
                            showWebcam 
                              ? 'bg-red-500/20 border border-red-500/50 text-red-400 hover:bg-red-500/30' 
                              : 'bg-blue-500/20 border border-blue-500/50 text-blue-400 hover:bg-blue-500/30'
                          }`}
                        >
                          {showWebcam ? (
                            <>
                              <X className="w-4 h-4" />
                              Close
                            </>
                          ) : (
                            <>
                              <Video className="w-4 h-4" />
                              Camera
                            </>
                          )}
                        </button>
                      </div>
                    </div>

                    {showWebcam && (
                      <div className="mb-6 bg-black/80 border border-cyan-500/30 rounded-xl p-4 overflow-hidden">
                        <div className="relative aspect-video bg-black rounded-lg overflow-hidden mb-4">
                          <video
                            ref={videoRef}
                            autoPlay
                            playsInline
                            muted
                            className="w-full h-full object-cover"
                          />
                          {!cameraStream && (
                            <div className="absolute inset-0 flex items-center justify-center bg-black/80">
                              <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
                            </div>
                          )}
                          {cameraError && (
                            <div className="absolute inset-0 flex items-center justify-center bg-black/80 p-4">
                              <div className="text-center">
                                <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-2" />
                                <p className="text-red-400 text-sm">{cameraError}</p>
                              </div>
                            </div>
                          )}
                        </div>
                        <canvas ref={canvasRef} className="hidden" />
                        <button
                          type="button"
                          onClick={capturePhoto}
                          disabled={images.length >= 10 || !cameraStream}
                          className="w-full px-6 py-3 bg-gradient-to-r from-cyan-600 to-blue-600 rounded-lg font-semibold hover:shadow-lg hover:shadow-cyan-500/50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-all"
                        >
                          <Camera className="w-5 h-5" />
                          Capture Photo {images.length >= 10 && '(Max reached)'}
                        </button>
                      </div>
                    )}

                    {!showWebcam && (
                      <label className="cursor-pointer block mb-6">
                        <div className="border-2 border-dashed border-purple-500/30 rounded-xl p-8 text-center hover:border-cyan-400/50 bg-black/40 transition-all hover:bg-black/60">
                          <Upload className="w-12 h-12 mx-auto mb-4 text-purple-400" />
                          <p className="text-sm text-gray-300 mb-2 font-semibold">Upload Images from Device</p>
                          <p className="text-xs text-gray-500">JPEG/PNG • Max 10 images</p>
                        </div>
                        <input
                          type="file"
                          accept="image/jpeg,image/png"
                          multiple
                          onChange={handleImageUpload}
                          disabled={images.length >= 10}
                          className="hidden"
                        />
                      </label>
                    )}

                    {imagePreviews.length > 0 && (
                      <div>
                        <div className="text-sm font-semibold text-purple-300 mb-3 uppercase tracking-wide">
                          Uploaded Images
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                          {imagePreviews.map((preview, i) => (
                            <div key={i} className="relative group">
                              <img
                                src={preview}
                                alt={`Preview ${i + 1}`}
                                className="w-full h-32 object-cover rounded-lg border-2 border-purple-500/30 group-hover:border-purple-400/60 transition-all"
                              />
                              <button
                                type="button"
                                onClick={() => removeImage(i)}
                                className="absolute top-2 right-2 p-1.5 bg-red-600 rounded-full opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-700"
                              >
                                <X className="w-4 h-4" />
                              </button>
                              <div className="absolute bottom-2 left-2 px-2 py-1 bg-black/80 rounded text-xs text-white font-semibold">
                                #{i + 1}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <button
                    type="submit"
                    disabled={loading || images.length === 0}
                    className="w-full px-8 py-4 bg-gradient-to-r from-purple-600 via-pink-600 to-cyan-600 rounded-xl font-bold text-lg hover:shadow-xl hover:shadow-purple-500/50 disabled:opacity-50 disabled:cursor-not-allowed uppercase tracking-wide flex justify-center items-center gap-3 transition-all"
                  >
                    {loading ? (
                      <>
                        <Loader2 className="w-6 h-6 animate-spin" />
                        {loadingStage || 'Processing...'}
                      </>
                    ) : (
                      <>
                        <Send className="w-6 h-6" />
                        Validate Product Compliance
                      </>
                    )}
                  </button>

                  {error && (
                    <div className="flex items-center gap-3 text-red-400 bg-red-900/20 border border-red-500/30 rounded-xl p-4">
                      <AlertCircle className="w-5 h-5 flex-shrink-0" />
                      <span>{error}</span>
                    </div>
                  )}
                </div>

                <div className="space-y-6">
                  <div className="bg-black/60 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-white mb-4">
                      <BarChart3 className="w-5 h-5 text-purple-400" />
                      Validation Info
                    </h3>
                    <div className="space-y-4">
                      <div className="flex items-center justify-between p-3 bg-black/40 rounded-lg border border-purple-500/20">
                        <span className="text-sm text-gray-400">Images</span>
                        <span className="text-lg font-bold text-purple-400">{images.length}/10</span>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-black/40 rounded-lg border border-purple-500/20">
                        <span className="text-sm text-gray-400">Description</span>
                        <span className="text-lg font-bold text-cyan-400">{description.length} chars</span>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-black/40 rounded-lg border border-purple-500/20">
                        <span className="text-sm text-gray-400">Category</span>
                        <span className="text-sm font-bold text-pink-400 uppercase">
                          {CATEGORIES.find(c => c.value === category)?.label.split(' ')[0]}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="bg-black/60 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-6 hover:border-cyan-400/50 transition-all">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-white mb-4">
                      <Info className="w-5 h-5 text-cyan-400" />
                      Guidelines
                    </h3>
                    <div className="space-y-3">
                      <div className="flex items-start gap-3">
                        <CheckCircle2 className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
                        <p className="text-sm text-gray-300">Upload clear, well-lit product images</p>
                      </div>
                      <div className="flex items-start gap-3">
                        <CheckCircle2 className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
                        <p className="text-sm text-gray-300">Include all product labels and certifications</p>
                      </div>
                      <div className="flex items-start gap-3">
                        <CheckCircle2 className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
                        <p className="text-sm text-gray-300">Provide detailed product description</p>
                      </div>
                      <div className="flex items-start gap-3">
                        <CheckCircle2 className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
                        <p className="text-sm text-gray-300">Add accurate weight and dimensions</p>
                      </div>
                    </div>
                  </div>

                  <div className="bg-gradient-to-br from-purple-900/20 to-pink-900/20 border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-white mb-3">
                      <Shield className="w-5 h-5 text-purple-400" />
                      Need Help?
                    </h3>
                    <p className="text-sm text-gray-300 mb-4">
                      Our AI will analyze your product for compliance with marketplace standards.
                    </p>
                    <button type="button" className="w-full px-4 py-2 bg-purple-500/20 border border-purple-500/50 rounded-lg text-purple-300 hover:bg-purple-500/30 transition-all text-sm font-semibold">
                      View Documentation
                    </button>
                  </div>
                </div>
              </div>
            </form>
          ) : (
            <div className="space-y-6">
              <div className={`rounded-xl border-2 p-8 ${getGradeBg(validationResult.compliance_grade)}`}>
                <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6 mb-6">
                  <div className="flex-1">
                    <h3 className="text-3xl font-bold mb-3 text-white">Compliance Report</h3>
                    <div className="flex flex-wrap gap-3">
                      <div className="px-3 py-1 bg-black/40 rounded-lg border border-purple-500/30">
                        <span className="text-xs text-gray-400 uppercase">Category:</span>
                        <span className="text-sm text-purple-300 font-semibold ml-2 uppercase">
                          {validationResult.category || 'N/A'}
                        </span>
                      </div>
                      <div className="px-3 py-1 bg-black/40 rounded-lg border border-purple-500/30">
                        <span className="text-xs text-gray-400 uppercase">Date:</span>
                        <span className="text-sm text-cyan-300 font-semibold ml-2">
                          {new Date(validationResult.analysis_date).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="text-center">
                      <div className={`text-6xl font-bold ${getGradeColor(validationResult.compliance_grade)}`}>
                        {validationResult.compliance_score || 0}
                      </div>
                      <div className="text-sm text-gray-400 uppercase tracking-wider mt-1">Score</div>
                    </div>
                    <div className="text-center">
                      <div className={`text-4xl font-bold ${getGradeColor(validationResult.compliance_grade)}`}>
                        {validationResult.compliance_grade || 'N/A'}
                      </div>
                      <div className="text-sm text-gray-400 uppercase tracking-wider mt-1">Grade</div>
                    </div>
                  </div>
                </div>

                {validationResult.violation_summary && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-red-900/20 border border-red-500/30 rounded-xl p-4 text-center hover:border-red-400/50 transition-all">
                      <XCircle className="w-8 h-8 text-red-400 mx-auto mb-2" />
                      <div className="text-3xl font-bold text-red-400">
                        {validationResult.violation_summary.high || 0}
                      </div>
                      <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">High Priority</div>
                    </div>
                    <div className="bg-amber-900/20 border border-amber-500/30 rounded-xl p-4 text-center hover:border-amber-400/50 transition-all">
                      <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto mb-2" />
                      <div className="text-3xl font-bold text-amber-400">
                        {validationResult.violation_summary.medium || 0}
                      </div>
                      <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">Medium Priority</div>
                    </div>
                    <div className="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4 text-center hover:border-blue-400/50 transition-all">
                      <Info className="w-8 h-8 text-blue-400 mx-auto mb-2" />
                      <div className="text-3xl font-bold text-blue-400">
                        {validationResult.violation_summary.low || 0}
                      </div>
                      <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">Low Priority</div>
                    </div>
                    <div className="bg-purple-900/20 border border-purple-500/30 rounded-xl p-4 text-center hover:border-purple-400/50 transition-all">
                      <Shield className="w-8 h-8 text-purple-400 mx-auto mb-2" />
                      <div className="text-3xl font-bold text-purple-400">
                        {validationResult.violation_summary.total || 0}
                      </div>
                      <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">Total Issues</div>
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
                  <div className={`rounded-xl p-4 border-2 ${
                    validationResult.ready_for_upload 
                      ? 'bg-green-900/20 border-green-500/50' 
                      : 'bg-red-900/20 border-red-500/50'
                  }`}>
                    <div className="flex items-center gap-3 mb-2">
                      {validationResult.ready_for_upload ? (
                        <CheckCircle2 className="w-6 h-6 text-green-400" />
                      ) : (
                        <XCircle className="w-6 h-6 text-red-400" />
                      )}
                      <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Ready for Upload</div>
                    </div>
                    <div className={`text-2xl font-bold ${
                      validationResult.ready_for_upload ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {validationResult.ready_for_upload ? 'YES' : 'NO'}
                    </div>
                  </div>
                  <div className="bg-cyan-900/20 border-2 border-cyan-500/50 rounded-xl p-4">
                    <div className="flex items-center gap-3 mb-2">
                      <TrendingUp className="w-6 h-6 text-cyan-400" />
                      <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Approval Chance</div>
                    </div>
                    <div className="text-2xl font-bold text-cyan-400">
                      {validationResult.estimated_approval_chance || 'Unknown'}
                    </div>
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                {renderIssues(validationResult.high_priority_issues, 'high', 'red', <XCircle className="w-5 h-5 text-red-400" />)}
                {renderIssues(validationResult.medium_priority_issues, 'medium', 'amber', <AlertTriangle className="w-5 h-5 text-amber-400" />)}
                {renderIssues(validationResult.low_priority_issues, 'low', 'blue', <Info className="w-5 h-5 text-blue-400" />)}
              </div>

              {validationResult.recommendations && validationResult.recommendations.length > 0 && (
                <div className="bg-gradient-to-br from-purple-900/20 to-cyan-900/20 border border-purple-500/30 rounded-xl p-6 hover:border-purple-400/50 transition-all">
                  <div className="flex items-center justify-between mb-4 cursor-pointer" onClick={() => toggleSection('recommendations')}>
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-cyan-500/20 rounded-lg border border-cyan-500/50">
                        <Star className="w-6 h-6 text-cyan-400" />
                      </div>
                      <h4 className="text-xl font-bold text-white uppercase tracking-wider">
                        Recommendations ({validationResult.recommendations.length})
                      </h4>
                    </div>
                    {expandedSections.recommendations ? <ChevronUp className="w-5 h-5 text-cyan-400" /> : <ChevronDown className="w-5 h-5 text-cyan-400" />}
                  </div>
                  {expandedSections.recommendations && (
                    <div className="mt-4 space-y-3">
                      {validationResult.recommendations.map((rec, i) => (
                        <div key={i} className="bg-black/60 border border-cyan-500/20 rounded-lg p-4 hover:bg-black/80 transition-all">
                          <div className="flex items-start gap-3">
                            <CheckCircle2 className="w-5 h-5 text-cyan-400 flex-shrink-0 mt-0.5" />
                            <div className="text-sm text-gray-300 leading-relaxed">{rec}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col sm:flex-row gap-4">
                <button
                  onClick={resetForm}
                  className="flex-1 px-6 py-4 bg-gradient-to-r from-purple-600 to-pink-600 rounded-xl font-semibold hover:shadow-lg hover:shadow-purple-500/50 transition-all uppercase flex items-center justify-center gap-2"
                >
                  <Plus className="w-5 h-5" />
                  New Validation
                </button>
                
                {validationResult.ready_for_upload && (
                  <button
                    onClick={() => alert('Proceed to marketplace upload!')}
                    className="flex-1 px-6 py-4 bg-gradient-to-r from-green-600 to-emerald-600 rounded-xl font-semibold hover:shadow-lg hover:shadow-green-500/50 transition-all uppercase flex items-center justify-center gap-2"
                  >
                    <CheckCircle2 className="w-5 h-5" />
                    Proceed to Upload
                  </button>
                )}
              </div>

              <div className="bg-black/60 border border-purple-500/30 rounded-xl p-6 text-center">
                <p className="text-sm text-gray-300">
                  {validationResult.ready_for_upload ? (
                    <span className="flex items-center justify-center gap-2">
                      <CheckCircle2 className="w-5 h-5 text-green-400" />
                      Your product meets compliance requirements and is ready for marketplace upload!
                    </span>
                  ) : (
                    <span className="flex items-center justify-center gap-2">
                      <AlertCircle className="w-5 h-5 text-amber-400" />
                      Please address the issues above before uploading to the marketplace.
                    </span>
                  )}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}