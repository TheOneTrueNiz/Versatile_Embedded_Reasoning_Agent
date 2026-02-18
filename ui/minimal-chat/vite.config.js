import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import VueDevTools from 'vite-plugin-vue-devtools';
import { VitePWA } from 'vite-plugin-pwa';
import viteImagemin from 'vite-plugin-imagemin';
import fs from 'fs';
import path from 'path';
import sharp from 'sharp';

// Get the directory name in ESM
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const hasBinary = (paths) => paths.some((p) => fs.existsSync(path.resolve(__dirname, p)));
const hasPngquant = hasBinary([
  'node_modules/pngquant-bin/vendor/pngquant',
  'node_modules/pngquant-bin/vendor/pngquant.exe',
  'node_modules/imagemin-pngquant/node_modules/pngquant-bin/vendor/pngquant',
  'node_modules/imagemin-pngquant/node_modules/pngquant-bin/vendor/pngquant.exe'
]);
const hasOptipng = hasBinary([
  'node_modules/optipng-bin/vendor/optipng',
  'node_modules/optipng-bin/vendor/optipng.exe'
]);
const hasMozjpeg = hasBinary([
  'node_modules/mozjpeg/vendor/cjpeg',
  'node_modules/mozjpeg/vendor/cjpeg.exe'
]);
const hasGifsicle = hasBinary([
  'node_modules/gifsicle/vendor/gifsicle',
  'node_modules/gifsicle/vendor/gifsicle.exe'
]);

// Recursive function to get all image files in a directory and its subdirectories
const getAllImageFiles = (dir) => {
  let results = [];
  const list = fs.readdirSync(dir);
  list.forEach((file) => {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);
    if (stat && stat.isDirectory()) {
      results = results.concat(getAllImageFiles(filePath));
    } else {
      if (filePath.toLowerCase().endsWith('.png')) {
        results.push(filePath);
      }
    }
  });

  return results;
};

// Function to generate icons array from images directory
const generateIcons = async () => {
  const imagesDir = path.resolve(__dirname, 'public/images');
  const files = getAllImageFiles(imagesDir);
  const icons = await Promise.all(files.map(async (file) => {
    try {
      const metadata = await sharp(file).metadata();
      const { width, height, format } = metadata;
      if (width === height && format === 'png') {
        const icon = {
          src: path.relative(path.resolve(__dirname, 'public'), file).replace(/\\/g, '/'),
          sizes: `${width}x${height}`,
          type: 'image/png'
        };
        if (file.includes('maskable')) {
          icon.purpose = 'maskable';
        }
        return icon;
      }
    } catch (error) {
      console.error(`Error processing file ${file}:`, error);
    }
  }));
  return icons.filter(Boolean);
};


const formatTagScreenshots = [
  {
    "src": "images/wide-minimal-chat.png",
    "sizes": "3832x2395",
    "type": "image/png",
    "form_factor": "wide",
    "label": "Desktop Homescreen of VERA"
  },
  {
    "src": "images/narrow-minimal-chat.png",
    "sizes": "860x1864",
    "type": "image/png",
    "form_factor": "narrow",
    "label": "Mobile Homescreen of VERA"
  }
];

// https://vitejs.dev/config/
export default defineConfig(async () => ({
  plugins: [
    vue(),
    viteImagemin({
      gifsicle: hasGifsicle ? {
        optimizationLevel: 7,
        interlaced: false,
      } : false,
      optipng: hasOptipng ? {
        optimizationLevel: 7,
      } : false,
      mozjpeg: hasMozjpeg ? {
        quality: 20,
      } : false,
      pngquant: hasPngquant ? {
        quality: [0.65, 0.9],
        speed: 4,
      } : false,
      svgo: {
        plugins: [
          {
            name: 'removeViewBox',
          },
          {
            name: 'removeEmptyAttrs',
            active: false,
          },
        ],
      },
    }),
    VueDevTools(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.js",
      injectManifest: {
        maximumFileSizeToCacheInBytes: 8000000,
      },
      manifest: {
        name: 'NizBot',
        short_name: 'VERA',
        description: 'VERA personal AI assistant',
        theme_color: '#202124',
        background_color: "#202124",
        icons: await generateIcons(),
        screenshots: formatTagScreenshots,
        edge_side_panel: {
          "preferred_width": 600
        }
      }
    })
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    }
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern'
      }
    }
  },
  build: {
    minify: 'terser', // Use Terser for more advanced minification
    terserOptions: {
      compress: {
        drop_console: true, // Remove console logs in production
        drop_debugger: true, // Remove debugger statements
        ecma: 2020, // Use modern ECMAScript features
        module: true,
        toplevel: true,
        passes: 10, // Multiple passes for better compression
      },
      format: {
        comments: false, // Remove comments
      },
    },
    target: 'esnext', // Target modern browsers for smaller bundle size
    cssCodeSplit: true, // Enable CSS code splitting
    sourcemap: false, // Disable source maps for production build
    chunkSizeWarningLimit: 6000, // Large optional libs (web-llm/pdfjs) are expected to exceed default
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return;
          const parts = id.toString().split('node_modules/')[1].split('/');
          const isScoped = parts[0].startsWith('@');
          const pkgName = isScoped ? `${parts[0]}/${parts[1]}` : parts[0];
          if (pkgName === 'vue' || pkgName.startsWith('@vue/')) return 'vue';
          if (pkgName === '@mlc-ai/web-llm') return 'web-llm';
          if (pkgName === 'pdfjs-dist') return 'pdfjs';
          if (pkgName === '@guolao/vue-monaco-editor' || pkgName === 'monaco-editor' || pkgName.startsWith('@monaco-editor')) {
            return 'monaco';
          }
          if (pkgName === 'primevue' || pkgName === 'primeicons' || pkgName === 'primeflex' || pkgName === '@primeuix/themes') {
            return 'prime';
          }
          return pkgName.replace('@', '').replace('/', '-');
        },
      },
    },
  },
}));
