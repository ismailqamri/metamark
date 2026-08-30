'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Poppins } from 'next/font/google';
import {
  Loader2,
  AlertCircle,
  MapPin,
  TrendingUp,
  Building2,
  Users,
  Activity,
  Clock,
  Globe,
  BarChart3,
  Filter,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  Package,
  Star,
  Calendar,
  ShoppingBag,
  Search,
  X,
  MousePointer2,
} from 'lucide-react';
import {
  GoogleMap,
  useJsApiLoader,
  Marker,
  InfoWindow,
  MarkerClusterer,
} from '@react-google-maps/api';
import Navbar from '../Navbar';

const poppins = Poppins({
  weight: ['400', '500', '600', '700'],
  subsets: ['latin'],
});

const API_BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5000';
const GOOGLE_MAPS_API_KEY = 'AIzaSyCRdKzY4bBefy0w3n_WUPC4uset4hED6hk';

const containerStyle = {
  width: '100%',
  height: '600px',
  borderRadius: '1rem',
};

const indiaCenter = {
  lat: 20.5937,
  lng: 78.9629,
};

const mapStyles = [
  { elementType: 'geometry', stylers: [{ color: '#0a0a0a' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#0a0a0a' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#746855' }] },
  {
    featureType: 'administrative.locality',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#a855f7' }],
  },
  { featureType: 'poi', elementType: 'labels.text.fill', stylers: [{ color: '#06b6d4' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#1a1a1a' }] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#212a37' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#2d1b4e' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0d1117' }] },
  { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#515c6d' }] },
];

const CITY_COORDINATES: Record<string, { lat: number; lng: number }> = {
  'Bengaluru, Karnataka, India': { lat: 12.9716, lng: 77.5946 },
  'Bangalore, Karnataka, India': { lat: 12.9716, lng: 77.5946 },
  'Mumbai, Maharashtra, India': { lat: 19.076, lng: 72.8777 },
  'Delhi, Delhi, India': { lat: 28.7041, lng: 77.1025 },
  'New Delhi, Delhi, India': { lat: 28.6139, lng: 77.2090 },
  'Hyderabad, Telangana, India': { lat: 17.385, lng: 78.4867 },
  'Chennai, Tamil Nadu, India': { lat: 13.0827, lng: 80.2707 },
  'Kolkata, West Bengal, India': { lat: 22.5726, lng: 88.3639 },
  'Pune, Maharashtra, India': { lat: 18.5204, lng: 73.8567 },
  'Ahmedabad, Gujarat, India': { lat: 23.0225, lng: 72.5714 },
  'Jaipur, Rajasthan, India': { lat: 26.9124, lng: 75.7873 },
  'Lucknow, Uttar Pradesh, India': { lat: 26.8467, lng: 80.9462 },
  'Gurgaon, Haryana, India': { lat: 28.4595, lng: 77.0266 },
  'Gurugram, Haryana, India': { lat: 28.4595, lng: 77.0266 },
  'Kyoto, Kyoto Prefecture, Japan': { lat: 35.0116, lng: 135.7681 },
  'Rajkot, Gujarat, India': { lat: 22.3039, lng: 70.8022 },
  'Bhodani, Maharashtra, India': { lat: 19.9975, lng: 73.7898 },
  'Meerut, Uttar Pradesh, India': { lat: 28.9845, lng: 77.7064 },
};

type Product = {
  title: string;
  rating: number | null;
  created_at: string;
  product_id: number;
  compliance_score: number | null;
};

type SellerPoint = {
  location: string;
  seller_name: string;
  total_scrapes: number;
  avg_compliance_score: number | string | null;
  last_activity: string;
  products: string; // JSON string
};

const extractCity = (location: string) => {
  const parts = location.split(',').map((p) => p.trim());
  return parts[0] || '';
};

const extractState = (location: string) => {
  const parts = location.split(',').map((p) => p.trim());
  return parts.length >= 2 ? parts[1] : '';
};

const getScoreColor = (score: number | null) => {
  if (score === null || score === 0) return '#6b7280';
  if (score < 40) return '#ef4444';
  if (score < 70) return '#f59e0b';
  if (score < 90) return '#eab308';
  return '#22c55e';
};

const parseProducts = (productsStr: string): Product[] => {
  try {
    return JSON.parse(productsStr);
  } catch {
    return [];
  }
};

const addOffsetToCoords = (lat: number, lng: number, index: number, total: number) => {
  if (total === 1) return { lat, lng };
  const radius = 0.002;
  const angle = (2 * Math.PI * index) / total;
  return {
    lat: lat + radius * Math.cos(angle),
    lng: lng + radius * Math.sin(angle),
  };
};

export default function HeatmapPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [userRole, setUserRole] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  const [heatmapData, setHeatmapData] = useState<any[]>([]);
  const [globalHeatmapData, setGlobalHeatmapData] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [viewMode, setViewMode] = useState<'user' | 'global'>('user');
  const [displayMode, setDisplayMode] = useState<'location' | 'product'>('location');

  const [selectedMarker, setSelectedMarker] = useState<any | null>(null);
  const [geocodedLocations, setGeocodedLocations] = useState(CITY_COORDINATES);
  const [expandedItem, setExpandedItem] = useState<number | null>(null);
  const [totalScrapes, setTotalScrapes] = useState(0);
  const [totalLocations, setTotalLocations] = useState(0);
  const [showHeatmap, setShowHeatmap] = useState(true);

  const [searchTerm, setSearchTerm] = useState('');
  const [productSearchTerm, setProductSearchTerm] = useState('');
  const [showLocationSuggestions, setShowLocationSuggestions] = useState(false);
  const [showProductSuggestions, setShowProductSuggestions] = useState(false);

  const [currentPage, setCurrentPage] = useState(1);
  const [stateFilter, setStateFilter] = useState<string>('all');
  const [cityFilter, setCityFilter] = useState<string>('all');
  const [complianceFilter, setComplianceFilter] = useState<string>('all');
  const PAGE_SIZE = 10;

  const mapRef = useRef<google.maps.Map | null>(null);
  const locationSearchRef = useRef<HTMLDivElement>(null);
  const productSearchRef = useRef<HTMLDivElement>(null);

  const { isLoaded } = useJsApiLoader({
    googleMapsApiKey: GOOGLE_MAPS_API_KEY,
    libraries: ['marker'],
  });

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        locationSearchRef.current &&
        !locationSearchRef.current.contains(event.target as Node)
      ) {
        setShowLocationSuggestions(false);
      }
      if (
        productSearchRef.current &&
        !productSearchRef.current.contains(event.target as Node)
      ) {
        setShowProductSuggestions(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  useEffect(() => {
    const userIdParam = searchParams.get('userId');
    const roleParam = searchParams.get('role');

    if (userIdParam && roleParam) {
      setUserId(parseInt(userIdParam));
      setUserRole(roleParam);
      setIsAuthenticated(true);
      localStorage.setItem('user_id', userIdParam);
      localStorage.setItem('user_role', roleParam);
      localStorage.setItem('isAuthenticated', 'true');
    } else {
      const storedUserId = localStorage.getItem('user_id');
      const storedRole = localStorage.getItem('user_role');
      const storedAuth = localStorage.getItem('isAuthenticated');

      if (storedUserId && storedRole && storedAuth === 'true') {
        setUserId(parseInt(storedUserId));
        setUserRole(storedRole);
        setIsAuthenticated(true);
      } else {
        setIsAuthenticated(false);
        setTimeout(() => {
          router.push('/auth/login');
        }, 2000);
      }
    }
  }, [searchParams, router]);

  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `
      ::-webkit-scrollbar { width: 8px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, rgba(168, 85, 247, 0.3), rgba(6, 182, 212, 0.3));
        border-radius: 10px;
        transition: all 0.3s ease;
      }
      ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(180deg, rgba(168, 85, 247, 0.6), rgba(6, 182, 212, 0.6));
      }
      * {
        scrollbar-width: thin;
        scrollbar-color: rgba(168, 85, 247, 0.3) transparent;
      }
    `;
    document.head.appendChild(style);
    return () => {
      document.head.removeChild(style);
    };
  }, []);

  const geocodeLocation = async (location: string) => {
    if (CITY_COORDINATES[location]) {
      return CITY_COORDINATES[location];
    }
    if (geocodedLocations[location]) {
      return geocodedLocations[location];
    }

    try {
      const response = await fetch(
        `https://maps.googleapis.com/maps/api/geocode/json?address=${encodeURIComponent(
          location
        )}&key=${GOOGLE_MAPS_API_KEY}`
      );
      const data = await response.json();

      if (data.status === 'OK' && data.results.length > 0) {
        const coords = {
          lat: data.results[0].geometry.location.lat,
          lng: data.results[0].geometry.location.lng,
        };
        setGeocodedLocations((prev) => ({ ...prev, [location]: coords }));
        return coords;
      }
    } catch (err) {
      console.error('[GEOCODE ERROR]', location, err);
    }
    return null;
  };

  const fetchUserHeatmap = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/heatmap`, {
        credentials: 'include',
      });

      if (!response.ok) {
        if (response.status === 401) {
          localStorage.clear();
          router.push('/auth/login');
          return;
        }
        throw new Error('Failed to fetch heatmap data');
      }

      const data = await response.json();
      setHeatmapData(data.heatmap_data || []);
      setTotalScrapes(data.total_scrapes || 0);
      setTotalLocations(data.total_locations || 0);

      for (const item of data.heatmap_data || []) {
        if (item.location) {
          await geocodeLocation(item.location);
        }
      }
    } catch (err: any) {
      console.error('[HEATMAP ERROR]', err);
      setError(err.message || 'Failed to fetch heatmap data');
    } finally {
      setLoading(false);
    }
  };

  const fetchGlobalHeatmap = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/global-heatmap`, {
        credentials: 'include',
      });

      if (!response.ok) {
        if (response.status === 401) {
          localStorage.clear();
          router.push('/auth/login');
          return;
        }
        throw new Error('Failed to fetch global heatmap data');
      }

      const data = await response.json();
      setGlobalHeatmapData(data.global_heatmap_data || []);
      setTotalScrapes(data.total_scrapes || 0);
      setTotalLocations(data.total_locations || 0);

      for (const item of data.global_heatmap_data || []) {
        if (item.location) {
          await geocodeLocation(item.location);
        }
      }
    } catch (err: any) {
      console.error('[GLOBAL HEATMAP ERROR]', err);
      setError(err.message || 'Failed to fetch global heatmap data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      if (viewMode === 'user') {
        fetchUserHeatmap();
      } else {
        fetchGlobalHeatmap();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, viewMode]);

  const formatDate = (dateStr: string) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  };

  const rawData: SellerPoint[] = useMemo(
    () => (viewMode === 'user' ? heatmapData : globalHeatmapData),
    [viewMode, heatmapData, globalHeatmapData]
  );

  // Extract all products across all sellers
  const allProducts = useMemo(() => {
    const products: Array<Product & { seller_name: string; location: string }> = [];
    rawData.forEach((seller) => {
      const sellerProducts = parseProducts(seller.products);
      sellerProducts.forEach((prod) => {
        products.push({
          ...prod,
          seller_name: seller.seller_name,
          location: seller.location,
        });
      });
    });
    return products;
  }, [rawData]);

  const stateOptions = useMemo(() => {
    const set = new Set<string>();
    rawData.forEach((row) => {
      const s = extractState(row.location || '');
      if (s && s !== 'Unknown' && s !== 'Unknown State') set.add(s);
    });
    return Array.from(set).sort();
  }, [rawData]);

  const cityOptions = useMemo(() => {
    const set = new Set<string>();
    rawData.forEach((row) => {
      const city = extractCity(row.location || '');
      const state = extractState(row.location || '');
      if (
        city &&
        state &&
        city !== 'Unknown' &&
        city !== 'Unknown City' &&
        state !== 'Unknown' &&
        state !== 'Unknown State'
      ) {
        set.add(`${city}, ${state}`);
      }
    });
    return Array.from(set).sort();
  }, [rawData]);

  // Location search suggestions
  const locationSuggestions = useMemo(() => {
    if (!searchTerm || searchTerm.length < 2) return [];

    const term = searchTerm.toLowerCase();
    const suggestions: Array<{
      type: 'seller' | 'location';
      text: string;
      subtitle: string;
      data: SellerPoint;
    }> = [];

    rawData.forEach((seller) => {
      const sellerMatch = seller.seller_name.toLowerCase().includes(term);
      const locationMatch = seller.location.toLowerCase().includes(term);

      if (sellerMatch || locationMatch) {
        suggestions.push({
          type: sellerMatch ? 'seller' : 'location',
          text: sellerMatch ? seller.seller_name : seller.location,
          subtitle: sellerMatch ? seller.location : `${parseProducts(seller.products).length} products`,
          data: seller,
        });
      }
    });

    return suggestions.slice(0, 8);
  }, [searchTerm, rawData]);

  // Product search suggestions
  const productSuggestions = useMemo(() => {
    if (!productSearchTerm || productSearchTerm.length < 2) return [];

    const term = productSearchTerm.toLowerCase();
    const suggestions: Array<{
      product: Product & { seller_name: string; location: string };
    }> = [];

    allProducts.forEach((product) => {
      if (product.title.toLowerCase().includes(term)) {
        suggestions.push({ product });
      }
    });

    return suggestions.slice(0, 8);
  }, [productSearchTerm, allProducts]);

  // Filter data based on display mode
  const filteredData = useMemo(() => {
    if (displayMode === 'location') {
      let data = [...rawData];

      if (stateFilter !== 'all') {
        data = data.filter((item) => extractState(item.location || '') === stateFilter);
      }

      if (cityFilter !== 'all') {
        const [cityName, stateName] = cityFilter.split(',').map((x) => x.trim());
        data = data.filter((item) => {
          const c = extractCity(item.location || '');
          const s = extractState(item.location || '');
          return c === cityName && s === stateName;
        });
      }

      if (searchTerm) {
        data = data.filter(
          (item) =>
            item.seller_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
            item.location.toLowerCase().includes(searchTerm.toLowerCase())
        );
      }

      return data;
    } else {
      // Product mode
      let products = [...allProducts];

      if (stateFilter !== 'all') {
        products = products.filter((item) => extractState(item.location || '') === stateFilter);
      }

      if (cityFilter !== 'all') {
        const [cityName, stateName] = cityFilter.split(',').map((x) => x.trim());
        products = products.filter((item) => {
          const c = extractCity(item.location || '');
          const s = extractState(item.location || '');
          return c === cityName && s === stateName;
        });
      }

      if (complianceFilter !== 'all') {
        if (complianceFilter === 'high') {
          products = products.filter((p) => (p.compliance_score || 0) >= 70);
        } else if (complianceFilter === 'medium') {
          products = products.filter(
            (p) => (p.compliance_score || 0) >= 40 && (p.compliance_score || 0) < 70
          );
        } else if (complianceFilter === 'low') {
          products = products.filter((p) => (p.compliance_score || 0) < 40);
        }
      }

      if (productSearchTerm) {
        products = products.filter(
          (item) =>
            item.title.toLowerCase().includes(productSearchTerm.toLowerCase()) ||
            item.seller_name.toLowerCase().includes(productSearchTerm.toLowerCase())
        );
      }

      return products;
    }
  }, [
    displayMode,
    rawData,
    allProducts,
    stateFilter,
    cityFilter,
    complianceFilter,
    searchTerm,
    productSearchTerm,
  ]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredData.length / PAGE_SIZE)),
    [filteredData.length]
  );

  const paginatedData = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredData.slice(start, start + PAGE_SIZE);
  }, [filteredData, currentPage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [stateFilter, cityFilter, complianceFilter, viewMode, displayMode, searchTerm, productSearchTerm]);

  const handleLocationSuggestionClick = (suggestion: any) => {
    setSearchTerm(suggestion.text);
    setShowLocationSuggestions(false);

    // Zoom to location on map
    if (mapRef.current) {
      const coords = geocodedLocations[suggestion.data.location];
      if (coords) {
        mapRef.current.panTo(coords);
        mapRef.current.setZoom(12);
      }
    }
  };

  const handleProductSuggestionClick = (product: any) => {
    setProductSearchTerm(product.product.title);
    setShowProductSuggestions(false);

    // Optionally zoom to product location on map
    if (mapRef.current) {
      const coords = geocodedLocations[product.product.location];
      if (coords) {
        mapRef.current.panTo(coords);
        mapRef.current.setZoom(12);
      }
    }
  };

  // NEW: Handle clicking on location card to zoom map
  const handleLocationCardClick = (seller: SellerPoint) => {
    if (mapRef.current) {
      const coords = geocodedLocations[seller.location];
      if (coords) {
        mapRef.current.panTo(coords);
        mapRef.current.setZoom(13);
        
        // Find and set the marker for this seller
        const marker = markers.find(
          (m) => m.seller_name === seller.seller_name && m.location === seller.location
        );
        if (marker) {
          setSelectedMarker(marker);
        }

        // Smooth scroll to map
        document.getElementById('heatmap-section')?.scrollIntoView({ 
          behavior: 'smooth', 
          block: 'center' 
        });
      }
    }
  };

  // NEW: Handle clicking on product card to zoom map
  const handleProductCardClick = (product: Product & { seller_name: string; location: string }) => {
    if (mapRef.current) {
      const coords = geocodedLocations[product.location];
      if (coords) {
        mapRef.current.panTo(coords);
        mapRef.current.setZoom(13);
        
        // Find and set the marker for this product's location
        const marker = markers.find(
          (m) => m.seller_name === product.seller_name && m.location === product.location
        );
        if (marker) {
          setSelectedMarker(marker);
        }

        // Smooth scroll to map
        document.getElementById('heatmap-section')?.scrollIntoView({ 
          behavior: 'smooth', 
          block: 'center' 
        });
      }
    }
  };

  const mapHeatmapData = useMemo(() => {
    if (!isLoaded || typeof window === 'undefined' || !showHeatmap) return [];

    return rawData
      .map((p) => {
        const coords = geocodedLocations[p.location];
        if (!coords) return null;
        const score = Number(p.avg_compliance_score) || 0;
        return {
          location: new window.google.maps.LatLng(coords.lat, coords.lng),
          weight: score > 0 ? score : 50,
        };
      })
      .filter(Boolean) as google.maps.visualization.WeightedLocation[];
  }, [isLoaded, showHeatmap, rawData, geocodedLocations]);

  const markers = useMemo(() => {
    const locationGroups = new Map<string, SellerPoint[]>();

    rawData.forEach((p) => {
      if (!locationGroups.has(p.location)) {
        locationGroups.set(p.location, []);
      }
      locationGroups.get(p.location)!.push(p);
    });

    const allMarkers: any[] = [];

    locationGroups.forEach((stores, location) => {
      const coords = geocodedLocations[location];
      if (!coords) return;

      stores.forEach((store, index) => {
        const score = Number(store.avg_compliance_score);
        const offsetCoords = addOffsetToCoords(coords.lat, coords.lng, index, stores.length);

        allMarkers.push({
          ...store,
          ...offsetCoords,
          type: 'seller',
          markerColor: getScoreColor(score),
          score: score || 0,
        });
      });
    });

    return allMarkers;
  }, [rawData, geocodedLocations]);

  const totalProducts = useMemo(() => {
    return rawData.reduce((sum, seller) => {
      return sum + parseProducts(seller.products).length;
    }, 0);
  }, [rawData]);

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
            <p className="text-gray-300 mb-4">
              Please log in to access this page. Redirecting to login...
            </p>
            <button
              onClick={() => router.push('/auth/login')}
              className="px-6 py-3 bg-gradient-to-r from-purple-600 to-cyan-600 rounded-lg font-semibold hover:shadow-[0_0_30px_rgba(168,85,247,0.5)] transition-all"
            >
              Go to Login
            </button>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      <div className="min-h-screen bg-black text-white p-8 ml-64">
        <div className="max-w-7xl mx-auto">
          <div className="mb-8 mt-6">
            <h2 className="text-4xl md:text-5xl font-bold mb-2">
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-cyan-400 tracking-tight">
                Activity Heatmap
              </span>
            </h2>
            <div
              className="border-t-2 [border-image:linear-gradient(to_right,theme(colors.purple.400),theme(colors.cyan.400))_1]"
              style={{ fontFamily: poppins.style.fontFamily }}
            />
            <div className="flex items-center justify-between mt-2">
              <p
                className={`text-xs ${poppins.className} tracking-wider uppercase text-gray-400`}
              >
                Geographic visualization of scraping & compliance activity
              </p>
              <div className={`text-xs ${poppins.className} text-cyan-400`}>
                User: <span className="font-mono">{userId}</span> | Role:{' '}
                <span className="font-semibold uppercase">{userRole}</span>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-4 mb-6">
            <div className="flex gap-4">
              <button
                onClick={() => setViewMode('user')}
                className={`px-6 py-3 rounded-xl font-semibold uppercase tracking-wider text-sm transition-all ${
                  viewMode === 'user'
                    ? 'bg-gradient-to-r from-purple-600 to-cyan-600 shadow-[0_0_30px_rgba(168,85,247,0.5)]'
                    : 'bg-black/40 border border-purple-500/30 hover:bg-purple-600/20'
                }`}
              >
                <MapPin className="w-4 h-4 inline mr-2" />
                My Activity
              </button>
              <button
                onClick={() => setViewMode('global')}
                className={`px-6 py-3 rounded-xl font-semibold uppercase tracking-wider text-sm transition-all ${
                  viewMode === 'global'
                    ? 'bg-gradient-to-r from-purple-600 to-cyan-600 shadow-[0_0_30px_rgba(168,85,247,0.5)]'
                    : 'bg-black/40 border border-purple-500/30 hover:bg-purple-600/20'
                }`}
              >
                <Globe className="w-4 h-4 inline mr-2" />
                Global Activity
              </button>
            </div>

            <div className="flex gap-4">
              <button
                onClick={() => setDisplayMode('location')}
                className={`px-6 py-3 rounded-xl font-semibold uppercase tracking-wider text-sm transition-all ${
                  displayMode === 'location'
                    ? 'bg-gradient-to-r from-green-600 to-teal-600 shadow-[0_0_30px_rgba(34,197,94,0.5)]'
                    : 'bg-black/40 border border-green-500/30 hover:bg-green-600/20'
                }`}
              >
                <Building2 className="w-4 h-4 inline mr-2" />
                By Location
              </button>
              <button
                onClick={() => setDisplayMode('product')}
                className={`px-6 py-3 rounded-xl font-semibold uppercase tracking-wider text-sm transition-all ${
                  displayMode === 'product'
                    ? 'bg-gradient-to-r from-green-600 to-teal-600 shadow-[0_0_30px_rgba(34,197,94,0.5)]'
                    : 'bg-black/40 border border-green-500/30 hover:bg-green-600/20'
                }`}
              >
                <Package className="w-4 h-4 inline mr-2" />
                By Product
              </button>
            </div>

            <div className="flex flex-wrap gap-3 items-center">
              {/* Search Bar with Suggestions */}
              <div className="relative flex-1 min-w-[200px]" ref={displayMode === 'location' ? locationSearchRef : productSearchRef}>
                <div className="flex items-center bg-black/40 border border-purple-500/40 rounded-xl px-3 py-2">
                  <Search className="w-4 h-4 text-purple-400 mr-2" />
                  <input
                    value={displayMode === 'location' ? searchTerm : productSearchTerm}
                    onChange={(e) => {
                      if (displayMode === 'location') {
                        setSearchTerm(e.target.value);
                        setShowLocationSuggestions(e.target.value.length >= 2);
                      } else {
                        setProductSearchTerm(e.target.value);
                        setShowProductSuggestions(e.target.value.length >= 2);
                      }
                    }}
                    onFocus={() => {
                      if (displayMode === 'location' && searchTerm.length >= 2) {
                        setShowLocationSuggestions(true);
                      } else if (displayMode === 'product' && productSearchTerm.length >= 2) {
                        setShowProductSuggestions(true);
                      }
                    }}
                    placeholder={
                      displayMode === 'location'
                        ? 'Search locations or sellers...'
                        : 'Search products...'
                    }
                    className="bg-transparent border-none outline-none text-sm text-white placeholder:text-gray-500 w-full"
                  />
                  {((displayMode === 'location' && searchTerm) ||
                    (displayMode === 'product' && productSearchTerm)) && (
                    <button
                      onClick={() => {
                        if (displayMode === 'location') {
                          setSearchTerm('');
                          setShowLocationSuggestions(false);
                        } else {
                          setProductSearchTerm('');
                          setShowProductSuggestions(false);
                        }
                      }}
                      className="ml-2"
                    >
                      <X className="w-4 h-4 text-gray-400 hover:text-white" />
                    </button>
                  )}
                </div>

                {/* Location Suggestions Dropdown */}
                {displayMode === 'location' && showLocationSuggestions && locationSuggestions.length > 0 && (
                  <div className="absolute z-30 mt-2 w-full bg-black/95 border border-purple-500/40 rounded-xl shadow-2xl max-h-80 overflow-auto">
                    {locationSuggestions.map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleLocationSuggestionClick(suggestion)}
                        className="w-full text-left px-4 py-3 hover:bg-purple-600/30 transition-all border-b border-purple-500/20 last:border-b-0"
                      >
                        <div className="flex items-center gap-3">
                          {suggestion.type === 'seller' ? (
                            <Building2 className="w-4 h-4 text-cyan-400 flex-shrink-0" />
                          ) : (
                            <MapPin className="w-4 h-4 text-purple-400 flex-shrink-0" />
                          )}
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold text-white truncate">
                              {suggestion.text}
                            </p>
                            <p className="text-xs text-gray-400 truncate">{suggestion.subtitle}</p>
                          </div>
                          <div
                            className="w-2 h-2 rounded-full flex-shrink-0"
                            style={{ backgroundColor: getScoreColor(Number(suggestion.data.avg_compliance_score)) }}
                          />
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {/* Product Suggestions Dropdown */}
                {displayMode === 'product' && showProductSuggestions && productSuggestions.length > 0 && (
                  <div className="absolute z-30 mt-2 w-full bg-black/95 border border-purple-500/40 rounded-xl shadow-2xl max-h-80 overflow-auto">
                    {productSuggestions.map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleProductSuggestionClick(suggestion)}
                        className="w-full text-left px-4 py-3 hover:bg-purple-600/30 transition-all border-b border-purple-500/20 last:border-b-0"
                      >
                        <div className="flex items-start gap-3">
                          <Package className="w-4 h-4 text-cyan-400 flex-shrink-0 mt-1" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold text-white line-clamp-2">
                              {suggestion.product.title}
                            </p>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="text-xs text-gray-400 truncate">
                                {suggestion.product.seller_name}
                              </span>
                              <span className="text-xs text-gray-600">•</span>
                              <span className="text-xs text-gray-400 truncate">
                                {suggestion.product.location}
                              </span>
                            </div>
                          </div>
                          <div
                            className="px-2 py-1 rounded text-xs font-bold flex-shrink-0"
                            style={{
                              backgroundColor: getScoreColor(suggestion.product.compliance_score),
                              color: '#fff',
                            }}
                          >
                            {suggestion.product.compliance_score?.toFixed(0) || 'N/A'}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <select
                value={stateFilter}
                onChange={(e) => {
                  setStateFilter(e.target.value);
                  setCityFilter('all');
                }}
                className="bg-black/40 border border-purple-500/40 rounded-xl px-4 py-2 text-xs uppercase tracking-wider focus:outline-none focus:border-cyan-400"
              >
                <option value="all">All States</option>
                {stateOptions.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>

              <select
                value={cityFilter}
                onChange={(e) => setCityFilter(e.target.value)}
                className="bg-black/40 border border-purple-500/40 rounded-xl px-4 py-2 text-xs uppercase tracking-wider focus:outline-none focus:border-cyan-400"
              >
                <option value="all">All Cities</option>
                {cityOptions.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>

              {displayMode === 'product' && (
                <select
                  value={complianceFilter}
                  onChange={(e) => setComplianceFilter(e.target.value)}
                  className="bg-black/40 border border-purple-500/40 rounded-xl px-4 py-2 text-xs uppercase tracking-wider focus:outline-none focus:border-cyan-400"
                >
                  <option value="all">All Compliance</option>
                  <option value="high">High (≥70)</option>
                  <option value="medium">Medium (40-69)</option>
                  <option value="low">Low (&lt;40)</option>
                </select>
              )}

              <button
                onClick={() => setShowHeatmap(!showHeatmap)}
                className={`px-4 py-2 rounded-xl font-semibold uppercase tracking-wider text-xs transition-all ${
                  showHeatmap
                    ? 'bg-green-600/20 border border-green-500/30'
                    : 'bg-black/40 border border-purple-500/30'
                }`}
              >
                <Activity className="w-4 h-4 inline mr-2" />
                {showHeatmap ? 'Hide' : 'Show'} Heatmap
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div className="bg-gradient-to-br from-purple-600/10 to-purple-900/10 border border-purple-500/30 rounded-xl p-6 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <div>
                  <p
                    className={`text-gray-400 text-xs uppercase tracking-wider ${poppins.className}`}
                  >
                    Total Stores
                  </p>
                  <p className="text-4xl font-bold text-white mt-2">{rawData.length}</p>
                </div>
                <Building2 className="w-12 h-12 text-purple-400 opacity-50" />
              </div>
            </div>

            <div className="bg-gradient-to-br from-cyan-600/10 to-cyan-900/10 border border-cyan-500/30 rounded-xl p-6 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <div>
                  <p
                    className={`text-gray-400 text-xs uppercase tracking-wider ${poppins.className}`}
                  >
                    Total Products
                  </p>
                  <p className="text-4xl font-bold text-white mt-2">{totalProducts}</p>
                </div>
                <Package className="w-12 h-12 text-cyan-400 opacity-50" />
              </div>
            </div>

            <div className="bg-gradient-to-br from-green-600/10 to-green-900/10 border border-green-500/30 rounded-xl p-6 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <div>
                  <p
                    className={`text-gray-400 text-xs uppercase tracking-wider ${poppins.className}`}
                  >
                    Total Scrapes
                  </p>
                  <p className="text-4xl font-bold text-white mt-2">
                    {totalScrapes.toLocaleString()}
                  </p>
                </div>
                <Activity className="w-12 h-12 text-green-400 opacity-50" />
              </div>
            </div>

            <div className="bg-gradient-to-br from-amber-600/10 to-amber-900/10 border border-amber-500/30 rounded-xl p-6 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <div>
                  <p
                    className={`text-gray-400 text-xs uppercase tracking-wider ${poppins.className}`}
                  >
                    Locations
                  </p>
                  <p className="text-4xl font-bold text-white mt-2">{totalLocations}</p>
                </div>
                <MapPin className="w-12 h-12 text-amber-400 opacity-50" />
              </div>
            </div>
          </div>

          {error && (
            <div className="mb-6 flex items-center gap-3 text-red-400 bg-red-900/20 border border-red-500/30 rounded-xl p-4">
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <span className={`${poppins.className} tracking-wide text-sm`}>{error}</span>
            </div>
          )}

          {loading && (
            <div className="mb-6 flex items-center gap-3 text-cyan-400">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className={`${poppins.className} tracking-wider uppercase text-sm`}>
                Loading heatmap data...
              </span>
            </div>
          )}

          <div id="heatmap-section" className="bg-black/60 border border-purple-500/30 rounded-2xl p-6 backdrop-blur-sm mb-8">
            <div className="flex items-center justify-between mb-4">
              <h3 className={`text-xl font-bold uppercase tracking-wider ${poppins.className}`}>
                Geographic Distribution ({markers.length} locations)
              </h3>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded-full bg-gray-500" />
                    <span>No Data</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded-full bg-red-500" />
                    <span>&lt; 40</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded-full bg-orange-500" />
                    <span>40–69</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded-full bg-yellow-500" />
                    <span>70–89</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded-full bg-green-500" />
                    <span>90–100</span>
                  </div>
                </div>
              </div>
            </div>

            {isLoaded ? (
              <GoogleMap
                mapContainerStyle={containerStyle}
                center={indiaCenter}
                zoom={5}
                onLoad={(map) => {
                  mapRef.current = map;
                }}
                options={{
                  styles: mapStyles,
                  disableDefaultUI: false,
                  zoomControl: true,
                  mapTypeControl: false,
                  streetViewControl: false,
                  fullscreenControl: true,
                }}
              >
                

                {markers.map((marker: any, idx: number) => (
                  <Marker
                    key={`marker-${idx}-${marker.seller_name}-${marker.lat}-${marker.lng}`}
                    position={{ lat: marker.lat, lng: marker.lng }}
                    onClick={() => setSelectedMarker(marker)}
                    label={{
                      text: marker.score ? marker.score.toFixed(0) : '0',
                      color: '#ffffff',
                      fontSize: '11px',
                      fontWeight: 'bold',
                    }}
                    icon={{
                      path: window.google.maps.SymbolPath.CIRCLE,
                      scale: 14,
                      fillColor: marker.markerColor,
                      fillOpacity: 0.95,
                      strokeColor: '#ffffff',
                      strokeWeight: 2,
                    }}
                  />
                ))}

                {selectedMarker && (
                  <InfoWindow
                    position={{ lat: selectedMarker.lat, lng: selectedMarker.lng }}
                    onCloseClick={() => setSelectedMarker(null)}
                  >
                    <div
                      className="bg-black/95 text-white p-4 rounded-lg min-w-[280px] max-w-[320px]"
                      style={{ background: '#0a0a0a', color: '#fff' }}
                    >
                      <h3 className={`font-bold text-sm mb-2 text-cyan-400 ${poppins.className}`}>
                        {selectedMarker.seller_name}
                      </h3>
                      <p className="text-xs text-gray-400 mb-2">📍 {selectedMarker.location}</p>
                      <div className="space-y-1 text-xs">
                        <p>
                          <span className="text-purple-400">Compliance Score:</span>{' '}
                          <span className="font-semibold">
                            {selectedMarker.score ? selectedMarker.score.toFixed(1) : '0.0'} / 100
                          </span>
                        </p>
                        <p>
                          <span className="text-amber-400">Total Scrapes:</span>{' '}
                          <span className="font-semibold">{selectedMarker.total_scrapes}</span>
                        </p>
                        <p>
                          <span className="text-cyan-400">Products:</span>{' '}
                          <span className="font-semibold">
                            {parseProducts(selectedMarker.products).length}
                          </span>
                        </p>
                        <p>
                          <span className="text-gray-400">Last Activity:</span>{' '}
                          <span className="font-mono text-[10px]">
                            {formatDate(selectedMarker.last_activity)}
                          </span>
                        </p>
                      </div>
                    </div>
                  </InfoWindow>
                )}
              </GoogleMap>
            ) : (
              <div className="flex items-center justify-center h-96 text-gray-500">
                <Loader2 className="w-8 h-8 animate-spin mr-3" />
                Loading map...
              </div>
            )}
          </div>

          <div className="bg-black/60 border border-purple-500/30 rounded-2xl backdrop-blur-sm overflow-hidden">
            <div className="bg-gradient-to-r from-purple-600/30 to-purple-700/30 rounded-t-xl p-4 border-b border-purple-500/40">
              <h3
                className={`text-base font-bold uppercase tracking-wider flex items-center gap-2 ${poppins.className}`}
              >
                {displayMode === 'location' ? (
                  <>
                    <Building2 className="w-5 h-5 text-purple-400" />
                    Location Details ({filteredData.length})
                  </>
                ) : (
                  <>
                    <Package className="w-5 h-5 text-purple-400" />
                    Product Details ({filteredData.length})
                  </>
                )}
              </h3>
              <p className="text-xs text-gray-400 mt-1 flex items-center gap-1">
                <MousePointer2 className="w-3 h-3" />
                Click on any card to view on map
              </p>
            </div>

            <div className="p-6 space-y-4">
              {filteredData.length === 0 && !loading && (
                <div className="text-center text-gray-500 py-12 uppercase tracking-wider text-sm">
                  No {displayMode === 'location' ? 'locations' : 'products'} found
                </div>
              )}

              {displayMode === 'location'
                ? paginatedData.map((item: any, idx: number) => {
                    const globalIndex = (currentPage - 1) * PAGE_SIZE + idx;
                    const score = Number(item.avg_compliance_score) || 0;
                    const products = parseProducts(item.products);

                    return (
                      <div
                        key={globalIndex}
                        className="bg-black/40 border border-purple-500/20 rounded-xl p-4 hover:border-cyan-400/50 transition-all cursor-pointer"
                        onClick={() => handleLocationCardClick(item)}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3 flex-1">
                            <div
                              className="w-3 h-3 rounded-full flex-shrink-0"
                              style={{ backgroundColor: getScoreColor(score) }}
                            />
                            <div className="flex-1">
                              <h4 className={`font-semibold text-white ${poppins.className} flex items-center gap-2`}>
                                {item.seller_name}
                                <MapPin className="w-3 h-3 text-cyan-400" />
                              </h4>
                              <p className="text-xs text-gray-400 mt-1">📍 {item.location}</p>
                              <div className="flex flex-wrap gap-4 mt-2 text-xs text-gray-400">
                                <span className="flex items-center gap-1">
                                  <Activity className="w-3 h-3" />
                                  Score: {score.toFixed(1)} / 100
                                </span>
                                <span className="flex items-center gap-1">
                                  <Package className="w-3 h-3" />
                                  {products.length} products
                                </span>
                                <span className="flex items-center gap-1">
                                  <Clock className="w-3 h-3" />
                                  {formatDate(item.last_activity)}
                                </span>
                              </div>
                            </div>
                          </div>

                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedItem(expandedItem === globalIndex ? null : globalIndex);
                            }}
                            className="ml-4 p-2 hover:bg-purple-600/20 rounded-lg transition-all"
                          >
                            {expandedItem === globalIndex ? (
                              <ChevronUp className="w-5 h-5 text-cyan-400" />
                            ) : (
                              <ChevronDown className="w-5 h-5 text-gray-400" />
                            )}
                          </button>
                        </div>

                        {expandedItem === globalIndex && (
                          <div className="mt-4 pt-4 border-t border-purple-500/20" onClick={(e) => e.stopPropagation()}>
                            <h5 className="text-sm font-semibold text-cyan-400 mb-3 flex items-center gap-2">
                              <Package className="w-4 h-4" />
                              Products ({products.length})
                            </h5>
                            <div className="space-y-2 max-h-64 overflow-auto">
                              {products.map((product, pIdx) => (
                                <div
                                  key={pIdx}
                                  className="bg-purple-600/10 rounded-lg p-3 border border-purple-500/20"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <p className="text-sm text-white flex-1">{product.title}</p>
                                    <div
                                      className="px-2 py-1 rounded text-xs font-bold"
                                      style={{
                                        backgroundColor: getScoreColor(product.compliance_score),
                                        color: '#fff',
                                      }}
                                    >
                                      {product.compliance_score?.toFixed(1) || 'N/A'}
                                    </div>
                                  </div>
                                  <div className="flex gap-4 mt-2 text-xs text-gray-400">
                                    <span>ID: {product.product_id}</span>
                                    <span className="flex items-center gap-1">
                                      <Calendar className="w-3 h-3" />
                                      {formatDate(product.created_at)}
                                    </span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                : paginatedData.map((product: any, idx: number) => {
                    const globalIndex = (currentPage - 1) * PAGE_SIZE + idx;
                    const score = product.compliance_score || 0;

                    return (
                      <div
                        key={globalIndex}
                        className="bg-black/40 border border-purple-500/20 rounded-xl p-4 hover:border-cyan-400/50 transition-all cursor-pointer"
                        onClick={() => handleProductCardClick(product)}
                      >
                        <div className="flex items-start gap-3">
                          <div
                            className="w-3 h-3 rounded-full flex-shrink-0 mt-1"
                            style={{ backgroundColor: getScoreColor(score) }}
                          />
                          <div className="flex-1">
                            <h4 className={`font-semibold text-white ${poppins.className} mb-2 flex items-center gap-2`}>
                              {product.title}
                              <MapPin className="w-3 h-3 text-cyan-400" />
                            </h4>
                            <div className="flex flex-wrap gap-4 text-xs text-gray-400 mb-2">
                              <span className="flex items-center gap-1">
                                <ShoppingBag className="w-3 h-3" />
                                {product.seller_name}
                              </span>
                              <span className="flex items-center gap-1">
                                <MapPin className="w-3 h-3" />
                                {product.location}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-4 text-xs text-gray-400">
                              <span className="flex items-center gap-1">
                                <Activity className="w-3 h-3" />
                                Compliance: {score.toFixed(1)} / 100
                              </span>
                              <span>ID: {product.product_id}</span>
                              <span className="flex items-center gap-1">
                                <Calendar className="w-3 h-3" />
                                {formatDate(product.created_at)}
                              </span>
                            </div>
                          </div>
                          <div
                            className="px-3 py-2 rounded-lg text-sm font-bold"
                            style={{
                              backgroundColor: getScoreColor(score) + '20',
                              color: getScoreColor(score),
                              border: `1px solid ${getScoreColor(score)}40`,
                            }}
                          >
                            {score.toFixed(1)}
                          </div>
                        </div>
                      </div>
                    );
                  })}

              {filteredData.length > 0 && (
                <div className="mt-6 flex items-center justify-between border-t border-purple-500/20 pt-4">
                  <span className="text-xs text-gray-400">
                    Page {currentPage} of {totalPages} · Showing {paginatedData.length} of{' '}
                    {filteredData.length} {displayMode === 'location' ? 'locations' : 'products'}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      disabled={currentPage === 1}
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                      className={`px-4 py-2 rounded-lg border text-xs uppercase tracking-wider flex items-center gap-1 transition-all ${
                        currentPage === 1
                          ? 'border-gray-600 text-gray-600 cursor-not-allowed'
                          : 'border-purple-500/40 text-purple-300 hover:bg-purple-600/20'
                      }`}
                    >
                      <ChevronLeft className="w-4 h-4" />
                      Prev
                    </button>
                    <button
                      disabled={currentPage === totalPages}
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                      className={`px-4 py-2 rounded-lg border text-xs uppercase tracking-wider flex items-center gap-1 transition-all ${
                        currentPage === totalPages
                          ? 'border-gray-600 text-gray-600 cursor-not-allowed'
                          : 'border-purple-500/40 text-purple-300 hover:bg-purple-600/20'
                      }`}
                    >
                      Next
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
