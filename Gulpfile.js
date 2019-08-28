var gulp = require("gulp");
var sass = require("gulp-sass");
var concat = require("gulp-concat");
var uglify = require("gulp-uglify");
var terser = require("gulp-terser");

var sassFiles = "./src/webswview/templates/default/src/sass/style.scss",
  cssDest = "./src/webswview/templates/default/static/css",
  jsDest = "./src/webswview/templates/default/static/js";

gulp.task("scripts", function() {
  return gulp
    .src([
      "./node_modules/jquery/dist/jquery.slim.js",
      "./node_modules/popper.js/dist/popper.js",
      "./node_modules/bootstrap/dist/js/bootstrap.js"
    ])
    .pipe(concat("concat.js"))
    .pipe(gulp.dest(jsDest))
    .pipe(terser())
    .pipe(gulp.dest(jsDest));
});

gulp.task("sass", function() {
  gulp
    .src(sassFiles)
    .pipe(sass().on("error", sass.logError))
    .pipe(concat("vendor.css"))
    .pipe(gulp.dest(cssDest));
});
gulp.task("watch", function() {
  gulp.watch(sassFiles, gulp.series("sass"));
});
